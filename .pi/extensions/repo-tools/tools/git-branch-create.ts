import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { runGit } from "../lib/git.ts";
import { withRepoMutationLock } from "../lib/mutex.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import { validateBranchName, validateOptionalRef, validateTimeoutSeconds } from "../lib/validation.ts";

const GitBranchCreateParams = Type.Object({
	branch: Type.String({ description: "New branch name. Must be a safe git branch name." }),
	start_point: Type.Optional(Type.String({ description: "Optional safe git ref/commit to branch from. Defaults to current HEAD." })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 30.", minimum: 5, maximum: 600 }),
	),
});

type GitBranchCreateInput = Static<typeof GitBranchCreateParams>;

export function createGitBranchCreateTool(pi: ExtensionAPI) {
	return defineTool({
		name: "git_branch_create",
		label: "Git Branch Create",
		description:
			"Create and switch to a new git branch using the fixed command `git switch -c <branch> [start_point]`. AFK-safe write tool with validated branch/ref inputs. No checkout/reset/raw args.",
		promptSnippet: "Create and switch to a new git branch safely without bash.",
		promptGuidelines: [
			"Use git_branch_create instead of bash when the user asks to create a new branch.",
			"Do not call git_branch_create in parallel with edit/write/git_commit/git_push/git_restore/gh_pr_create.",
		],
		parameters: GitBranchCreateParams,

		async execute(_toolCallId, params: GitBranchCreateInput, signal, onUpdate, ctx) {
			return withRepoMutationLock(async () => {
				const branch = validateBranchName(params.branch);
				const startPoint = validateOptionalRef(params.start_point, "start_point");
				const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 30);
				const args = ["switch", "-c", branch];
				if (startPoint) args.push(startPoint);
				const displayCommand = formatArgv("git", args);
				onUpdate?.({ content: [{ type: "text", text: `Running ${displayCommand}` }], details: {} });

				const result = await runGit(pi, args, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
				const prefix = [
					`Command: ${displayCommand}`,
					`Exit code: ${result.code}`,
					`Status: ${result.code === 0 ? "ok" : "failed"}`,
					`Duration: ${formatDuration(result.durationMs)}`,
					result.killed ? "Process was killed (timeout or cancellation)." : undefined,
				]
					.filter(Boolean)
					.join("\n");
				const formatted = await formatCommandOutput(mergeOutput(result.stdout, result.stderr), prefix);

				return {
					content: [{ type: "text", text: formatted.text }],
					details: {
						tool: "git_branch_create",
						command: "git",
						args,
						branch,
						startPoint,
						exitCode: result.code,
						killed: result.killed,
						durationMs: result.durationMs,
						...formatted.details,
					},
				};
			});
		},
	});
}
