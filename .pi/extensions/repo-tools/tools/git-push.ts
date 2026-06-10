import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { requireCurrentBranch, runGit } from "../lib/git.ts";
import { withRepoMutationLock } from "../lib/mutex.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import { validateTimeoutSeconds } from "../lib/validation.ts";

const GitPushParams = Type.Object({
	set_upstream: Type.Optional(
		Type.Boolean({ description: "Push with `--set-upstream origin <current-branch>`. Defaults to true." }),
	),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 120.", minimum: 5, maximum: 600 }),
	),
});

type GitPushInput = Static<typeof GitPushParams>;

export function createGitPushTool(pi: ExtensionAPI) {
	return defineTool({
		name: "git_push",
		label: "Git Push",
		description:
			"Push the current branch to origin using fixed `git push [--set-upstream] origin <current-branch>`. AFK-safe write/network tool. No force push, no arbitrary remote/branch.",
		promptSnippet: "Push the current git branch to origin safely without bash.",
		promptGuidelines: [
			"Use git_push instead of bash when the user asks to push committed changes.",
			"git_push only pushes the current branch to origin and never force-pushes.",
			"Do not call git_push in parallel with edit/write/git_branch_create/git_commit/git_restore/gh_pr_create.",
		],
		parameters: GitPushParams,

		async execute(_toolCallId, params: GitPushInput, signal, onUpdate, ctx) {
			return withRepoMutationLock(async () => {
				const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 120);
				const branch = await requireCurrentBranch(pi, ctx.cwd, signal);
				const setUpstream = params.set_upstream ?? true;
				const args = ["push"];
				if (setUpstream) args.push("--set-upstream");
				args.push("origin", branch);
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
						tool: "git_push",
						command: "git",
						args,
						remote: "origin",
						branch,
						setUpstream,
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
