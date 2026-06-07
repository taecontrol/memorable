import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { requireCurrentBranch } from "../lib/git.ts";
import { runGh } from "../lib/gh.ts";
import { withRepoMutationLock } from "../lib/mutex.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import { validateBody, validateBranchName, validateGithubRepo, validateTimeoutSeconds, validateTitle } from "../lib/validation.ts";

const GhPrCreateParams = Type.Object({
	title: Type.String({ description: "Pull request title." }),
	body: Type.Optional(Type.String({ description: "Pull request body. Defaults to empty string." })),
	base: Type.Optional(Type.String({ description: "Base branch. Defaults to gh's repository default/base detection." })),
	repo: Type.Optional(Type.String({ description: "GitHub repo as owner/name. Defaults to current repository." })),
	draft: Type.Optional(Type.Boolean({ description: "Create the PR as a draft. Defaults to false." })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 120.", minimum: 5, maximum: 600 }),
	),
});

type GhPrCreateInput = Static<typeof GhPrCreateParams>;

export function createGhPrCreateTool(pi: ExtensionAPI) {
	return defineTool({
		name: "gh_pr_create",
		label: "GitHub PR Create",
		description:
			"Create a GitHub pull request using fixed `gh pr create` arguments from the current branch. AFK-safe write/network tool. No arbitrary gh passthrough.",
		promptSnippet: "Create a GitHub pull request from the current branch safely without bash.",
		promptGuidelines: [
			"Use gh_pr_create instead of bash for creating pull requests after git_push.",
			"Call git_push before gh_pr_create when the current branch has not been pushed.",
			"Do not call gh_pr_create in parallel with edit/write/git_branch_create/git_commit/git_push/git_restore.",
		],
		parameters: GhPrCreateParams,

		async execute(_toolCallId, params: GhPrCreateInput, signal, onUpdate, ctx) {
			return withRepoMutationLock(async () => {
				const title = validateTitle(params.title);
				const body = validateBody(params.body) ?? "";
				const base = params.base === undefined ? undefined : validateBranchName(params.base, "base");
				const repo = validateGithubRepo(params.repo);
				const draft = params.draft ?? false;
				const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 120);
				const head = await requireCurrentBranch(pi, ctx.cwd, signal);

				const args = ["pr", "create", "--title", title, "--body", body, "--head", head];
				if (base) args.push("--base", base);
				if (repo) args.push("--repo", repo);
				if (draft) args.push("--draft");

				const displayCommand = formatArgv("gh", args);
				onUpdate?.({ content: [{ type: "text", text: `Running ${displayCommand}` }], details: {} });

				const result = await runGh(pi, args, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
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
						tool: "gh_pr_create",
						command: "gh",
						args,
						title,
						base,
						repo,
						head,
						draft,
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
