import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { runGh, parseGhJson, requireCurrentGitHubRepo } from "../lib/gh.ts";
import { parseIssueInput } from "../lib/parse.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import {
	requirePositiveSafeInteger,
	validateGithubRepo,
	validateIssueRef,
	validateTimeoutSeconds,
} from "../lib/validation.ts";

const GhIssueViewParams = Type.Object({
	issue: Type.Optional(
		Type.String({ description: "Issue reference: number, #number, owner/repo#number, or GitHub issue URL." }),
	),
	repo: Type.Optional(Type.String({ description: "GitHub repo as owner/name. Defaults to current repository." })),
	number: Type.Optional(Type.Integer({ description: "Issue number. Use either issue or number, not both.", minimum: 1 })),
	comments: Type.Optional(Type.Boolean({ description: "Include issue comments. Defaults to false." })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 60.", minimum: 5, maximum: 600 }),
	),
});

type GhIssueViewInput = Static<typeof GhIssueViewParams>;

type IssuePayload = {
	number?: number;
	title?: string;
	body?: string;
	state?: string;
	url?: string;
	labels?: Array<{ name?: string }>;
	comments?: Array<{ author?: { login?: string }; body?: string; createdAt?: string; url?: string }>;
};

export function createGhIssueViewTool(pi: ExtensionAPI) {
	return defineTool({
		name: "gh_issue_view",
		label: "GitHub Issue View",
		description:
			"Read a GitHub issue via the fixed command `gh issue view`. Accepts issue refs or repo+number; returns title/body/labels/state/url and optional comments. No arbitrary gh passthrough.",
		promptSnippet: "Read GitHub issues safely without bash or arbitrary gh commands.",
		promptGuidelines: [
			"Use gh_issue_view instead of bash for `gh issue view`.",
			"Use gh_issue_view with comments=true only when comments are needed; otherwise keep output smaller.",
		],
		parameters: GhIssueViewParams,

		async execute(_toolCallId, params: GhIssueViewInput, signal, onUpdate, ctx) {
			const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 60);
			const { repo, number } = await resolveIssueRef(pi, params, ctx.cwd, signal);
			const includeComments = params.comments ?? false;
			const fields = includeComments ? "number,title,body,labels,state,comments,url" : "number,title,body,labels,state,url";
			const args = ["issue", "view", String(number), "--repo", repo];
			if (includeComments) args.push("--comments");
			args.push("--json", fields);

			const displayCommand = formatArgv("gh", args);
			onUpdate?.({ content: [{ type: "text", text: `Running ${displayCommand}` }], details: {} });

			const result = await runGh(pi, args, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
			if (result.code !== 0) {
				const prefix = [
					`Command: ${displayCommand}`,
					`Exit code: ${result.code}`,
					"Status: failed",
					`Duration: ${formatDuration(result.durationMs)}`,
					result.killed ? "Process was killed (timeout or cancellation)." : undefined,
				]
					.filter(Boolean)
					.join("\n");
				const formatted = await formatCommandOutput(mergeOutput(result.stdout, result.stderr), prefix);
				return {
					content: [{ type: "text", text: formatted.text }],
					details: {
						tool: "gh_issue_view",
						command: "gh",
						args,
						repo,
						number,
						exitCode: result.code,
						killed: result.killed,
						durationMs: result.durationMs,
						...formatted.details,
					},
				};
			}

			const issue = parseGhJson<IssuePayload>(result, displayCommand);
			const formattedIssue = formatIssue(issue, repo, includeComments);
			const prefix = [
				`Command: ${displayCommand}`,
				`Exit code: ${result.code}`,
				"Status: ok",
				`Duration: ${formatDuration(result.durationMs)}`,
			]
				.filter(Boolean)
				.join("\n");
			const formatted = await formatCommandOutput(formattedIssue, prefix);

			return {
				content: [{ type: "text", text: formatted.text }],
				details: {
					tool: "gh_issue_view",
					command: "gh",
					args,
					repo,
					number,
					includeComments,
					exitCode: result.code,
					killed: result.killed,
					durationMs: result.durationMs,
					issue,
					...formatted.details,
				},
			};
		},
	});
}

async function resolveIssueRef(
	pi: ExtensionAPI,
	params: GhIssueViewInput,
	cwd: string,
	signal?: AbortSignal,
): Promise<{ repo: string; number: number }> {
	if (params.issue !== undefined && params.number !== undefined) throw new Error("Use either issue or number, not both.");
	const explicitRepo = validateGithubRepo(params.repo);
	const defaultRepo = explicitRepo ?? (await requireCurrentGitHubRepo(pi, cwd, signal));

	const issueRef = validateIssueRef(params.issue);
	if (issueRef !== undefined) return parseIssueInput(issueRef, defaultRepo);

	const number = requirePositiveSafeInteger(params.number, "number");
	return { repo: defaultRepo, number };
}

function formatIssue(issue: IssuePayload, repo: string, includeComments: boolean): string {
	const labels = issue.labels?.map((label) => label.name).filter(Boolean).join(", ") || "none";
	const lines = [
		`Repo: ${repo}`,
		`Issue: #${issue.number ?? "unknown"}`,
		`Title: ${issue.title ?? ""}`,
		`State: ${issue.state ?? ""}`,
		`Labels: ${labels}`,
		issue.url ? `URL: ${issue.url}` : undefined,
		"",
		issue.body ?? "",
	].filter((line): line is string => line !== undefined);

	if (includeComments) {
		const comments = issue.comments ?? [];
		lines.push("", `Comments: ${comments.length}`);
		for (const comment of comments) {
			lines.push("", `--- ${comment.author?.login ?? "unknown"} ${comment.createdAt ?? ""} ---`);
			if (comment.url) lines.push(`URL: ${comment.url}`);
			lines.push(comment.body ?? "");
		}
	}

	return lines.join("\n");
}
