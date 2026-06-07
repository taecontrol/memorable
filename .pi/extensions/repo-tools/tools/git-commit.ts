import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { runGit } from "../lib/git.ts";
import { withRepoMutationLock } from "../lib/mutex.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import { validateCommitMessage, validateRepoPaths, validateTimeoutSeconds } from "../lib/validation.ts";

const GitCommitParams = Type.Object({
	message: Type.String({ description: "Commit message. Must not include a Co-authored-by: Claude trailer." }),
	paths: Type.Optional(
		Type.Array(Type.String({ description: "Repo-relative path to stage before committing." }), {
			description: "Optional repo-relative paths to stage. If omitted and all=true, stages all changes with `git add -A`.",
			maxItems: 50,
		}),
	),
	all: Type.Optional(Type.Boolean({ description: "When paths is omitted, stage all changes with `git add -A` before committing. Defaults to true." })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 60.", minimum: 5, maximum: 600 }),
	),
});

type GitCommitInput = Static<typeof GitCommitParams>;

export function createGitCommitTool(pi: ExtensionAPI) {
	return defineTool({
		name: "git_commit",
		label: "Git Commit",
		description:
			"Stage validated changes and create a git commit. Uses `git add -A` or `git add -- <paths>` followed by `git commit -m <message>`. AFK-safe write tool with constrained staging. Rejects Co-authored-by: Claude trailers.",
		promptSnippet: "Stage changes and commit safely without bash.",
		promptGuidelines: [
			"Use git_commit instead of bash for staging and committing changes when the user asks for a commit.",
			"Do not include Co-Authored-By: Claude or similar AI co-author trailers in git_commit messages.",
			"Do not call git_commit in parallel with edit/write/git_branch_create/git_push/git_restore/gh_pr_create.",
		],
		parameters: GitCommitParams,

		async execute(_toolCallId, params: GitCommitInput, signal, onUpdate, ctx) {
			return withRepoMutationLock(async () => {
				const message = validateCommitMessage(params.message);
				const paths = validateRepoPaths(ctx.cwd, params.paths);
				const stageAll = params.all ?? true;
				const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 60);

				const outputs: string[] = [];
				const commandDetails: Array<{ args: string[]; exitCode: number; killed: boolean; durationMs: number }> = [];
				if (paths.length > 0 || stageAll) {
					const addArgs = paths.length > 0 ? ["add", "--", ...paths] : ["add", "-A"];
					const addCommand = formatArgv("git", addArgs);
					onUpdate?.({ content: [{ type: "text", text: `Running ${addCommand}` }], details: {} });
					const addResult = await runGit(pi, addArgs, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
					commandDetails.push({ args: addArgs, exitCode: addResult.code, killed: addResult.killed, durationMs: addResult.durationMs });
					outputs.push(`${addCommand}\nexitCode=${addResult.code}\n${mergeOutput(addResult.stdout, addResult.stderr).trimEnd()}`.trimEnd());
					if (addResult.code !== 0) {
						const formatted = await formatCommandOutput(outputs.join("\n\n"), formatPrefix(commandDetails));
						return makeResult(commandDetails, formatted, message, paths, stageAll);
					}
				}

				const commitArgs = ["commit", "-m", message];
				const commitCommand = formatArgv("git", commitArgs);
				onUpdate?.({ content: [{ type: "text", text: `Running ${commitCommand}` }], details: {} });
				const commitResult = await runGit(pi, commitArgs, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
				commandDetails.push({ args: commitArgs, exitCode: commitResult.code, killed: commitResult.killed, durationMs: commitResult.durationMs });
				outputs.push(`${commitCommand}\nexitCode=${commitResult.code}\n${mergeOutput(commitResult.stdout, commitResult.stderr).trimEnd()}`.trimEnd());

				const formatted = await formatCommandOutput(outputs.join("\n\n"), formatPrefix(commandDetails));
				return makeResult(commandDetails, formatted, message, paths, stageAll);
			});
		},
	});
}

function formatPrefix(commandDetails: Array<{ args: string[]; exitCode: number; killed: boolean; durationMs: number }>): string {
	const totalDurationMs = commandDetails.reduce((total, detail) => total + detail.durationMs, 0);
	const ok = commandDetails.every((detail) => detail.exitCode === 0);
	return [
		`Commands: ${commandDetails.map((detail) => formatArgv("git", detail.args)).join(" && ")}`,
		`Exit codes: ${commandDetails.map((detail) => detail.exitCode).join(", ")}`,
		`Status: ${ok ? "ok" : "failed"}`,
		`Duration: ${formatDuration(totalDurationMs)}`,
		commandDetails.some((detail) => detail.killed) ? "Process was killed (timeout or cancellation)." : undefined,
	]
		.filter(Boolean)
		.join("\n");
}

function makeResult(
	commandDetails: Array<{ args: string[]; exitCode: number; killed: boolean; durationMs: number }>,
	formatted: Awaited<ReturnType<typeof formatCommandOutput>>,
	message: string,
	paths: string[],
	stageAll: boolean,
) {
	return {
		content: [{ type: "text" as const, text: formatted.text }],
		details: {
			tool: "git_commit",
			command: "git",
			commands: commandDetails,
			message,
			paths,
			stageAll,
			exitCode: commandDetails.at(-1)?.exitCode,
			killed: commandDetails.some((detail) => detail.killed),
			durationMs: commandDetails.reduce((total, detail) => total + detail.durationMs, 0),
			...formatted.details,
		},
	};
}
