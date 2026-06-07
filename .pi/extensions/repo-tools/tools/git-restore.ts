import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { runGit } from "../lib/git.ts";
import { withRepoMutationLock } from "../lib/mutex.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import { validateRequiredRepoPaths, validateTimeoutSeconds } from "../lib/validation.ts";

const GitRestoreParams = Type.Object({
	paths: Type.Array(Type.String({ description: "Repo-relative path to restore." }), {
		description: "Repo-relative paths to restore. Required. Max 50.",
		maxItems: 50,
	}),
	staged: Type.Optional(Type.Boolean({ description: "Restore staged/index state (`--staged`). Defaults to false." })),
	worktree: Type.Optional(
		Type.Boolean({ description: "Restore working tree state (`--worktree`). Defaults to true when staged=false, false when staged=true." }),
	),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 30.", minimum: 5, maximum: 600 }),
	),
});

type GitRestoreInput = Static<typeof GitRestoreParams>;

export function createGitRestoreTool(pi: ExtensionAPI) {
	return defineTool({
		name: "git_restore",
		label: "Git Restore",
		description:
			"Restore validated repo paths using fixed `git restore` arguments. AFK-safe but destructive write tool for explicit restore requests. Replaces historical `git checkout -- <paths>` usage. No reset/checkout/raw args.",
		promptSnippet: "Restore selected git-tracked paths safely without bash.",
		promptGuidelines: [
			"Use git_restore instead of bash `git checkout -- <paths>` when the user asks to discard selected changes.",
			"git_restore is destructive; inspect changes with git_inspect before using it unless the user explicitly requested a restore.",
			"Do not call git_restore in parallel with edit/write/git_branch_create/git_commit/git_push/gh_pr_create.",
		],
		parameters: GitRestoreParams,

		async execute(_toolCallId, params: GitRestoreInput, signal, onUpdate, ctx) {
			return withRepoMutationLock(async () => {
				const paths = validateRequiredRepoPaths(ctx.cwd, params.paths);
				const staged = params.staged ?? false;
				const worktree = params.worktree ?? !staged;
				if (!staged && !worktree) throw new Error("At least one of staged/worktree must be true.");
				const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 30);
				const args = ["restore"];
				if (staged) args.push("--staged");
				if (worktree) args.push("--worktree");
				args.push("--", ...paths);
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
						tool: "git_restore",
						command: "git",
						args,
						paths,
						staged,
						worktree,
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
