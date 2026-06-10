import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { parseGhJson, requireCurrentGitHubRepo, runGh } from "../lib/gh.ts";
import { parseActionsRunUrl } from "../lib/parse.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import {
	requirePositiveSafeInteger,
	validateGithubRepo,
	validatePositiveSafeInteger,
	validateTimeoutSeconds,
} from "../lib/validation.ts";

const GhRunInspectParams = Type.Object({
	url: Type.Optional(
		Type.String({ description: "GitHub Actions run or job URL, e.g. https://github.com/owner/repo/actions/runs/<run-id>/job/<job-id>." }),
	),
	repo: Type.Optional(Type.String({ description: "GitHub repo as owner/name. Defaults to current repository when url is omitted." })),
	run_id: Type.Optional(Type.Integer({ description: "GitHub Actions run id. Required when url is omitted.", minimum: 1 })),
	job_id: Type.Optional(Type.Integer({ description: "Optional GitHub Actions job id for focused failed logs.", minimum: 1 })),
	failed_logs: Type.Optional(Type.Boolean({ description: "Include failed-step logs using `gh run view --log-failed`. Defaults to true." })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 120.", minimum: 5, maximum: 600 }),
	),
});

type GhRunInspectInput = Static<typeof GhRunInspectParams>;

type RunPayload = {
	attempt?: number;
	conclusion?: string;
	createdAt?: string;
	databaseId?: number;
	event?: string;
	headBranch?: string;
	headSha?: string;
	jobs?: Array<{ databaseId?: number; name?: string; status?: string; conclusion?: string; url?: string }>;
	name?: string;
	status?: string;
	updatedAt?: string;
	url?: string;
	workflowName?: string;
};

export function createGhRunInspectTool(pi: ExtensionAPI) {
	return defineTool({
		name: "gh_run_inspect",
		label: "GitHub Run Inspect",
		description:
			"Inspect a GitHub Actions run/job URL using fixed `gh run view` commands. Returns run status/conclusion/jobs and, by default, failed-step logs. No arbitrary gh passthrough.",
		promptSnippet: "Inspect GitHub Actions run failures and failed logs safely without bash.",
		promptGuidelines: [
			"Use gh_run_inspect when the user shares a GitHub Actions run/job URL or asks why CI failed.",
			"Call gh_run_inspect again after pushing fixes to check the latest status; Phase 1 intentionally does not watch/block on runs.",
		],
		parameters: GhRunInspectParams,

		async execute(_toolCallId, params: GhRunInspectInput, signal, onUpdate, ctx) {
			const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 120);
			const ref = await resolveRunRef(pi, params, ctx.cwd, signal);
			const fields = "attempt,conclusion,createdAt,databaseId,event,headBranch,headSha,jobs,name,status,updatedAt,url,workflowName";
			const statusArgs = ["run", "view", String(ref.runId), "--repo", ref.repo, "--json", fields];
			const statusCommand = formatArgv("gh", statusArgs);
			onUpdate?.({ content: [{ type: "text", text: `Running ${statusCommand}` }], details: {} });

			const statusResult = await runGh(pi, statusArgs, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
			if (statusResult.code !== 0) {
				const prefix = formatRunCommandPrefix(statusCommand, statusResult.code, statusResult.durationMs, statusResult.killed);
				const formatted = await formatCommandOutput(mergeOutput(statusResult.stdout, statusResult.stderr), prefix);
				return {
					content: [{ type: "text", text: formatted.text }],
					details: {
						tool: "gh_run_inspect",
						repo: ref.repo,
						runId: ref.runId,
						jobId: ref.jobId,
						statusArgs,
						statusExitCode: statusResult.code,
						statusDurationMs: statusResult.durationMs,
						...formatted.details,
					},
				};
			}

			const run = parseGhJson<RunPayload>(statusResult, statusCommand);
			const includeLogs = params.failed_logs ?? true;
			let logsResult: Awaited<ReturnType<typeof runGh>> | undefined;
			let logsArgs: string[] | undefined;
			let logsCommand: string | undefined;
			if (includeLogs) {
				logsArgs = ref.jobId
					? ["run", "view", "--job", String(ref.jobId), "--repo", ref.repo, "--log-failed"]
					: ["run", "view", String(ref.runId), "--repo", ref.repo, "--log-failed"];
				logsCommand = formatArgv("gh", logsArgs);
				onUpdate?.({ content: [{ type: "text", text: `Running ${logsCommand}` }], details: {} });
				logsResult = await runGh(pi, logsArgs, { cwd: ctx.cwd, signal, timeoutMs: timeoutSeconds * 1000 });
			}

			const logsOutput = logsResult ? mergeOutput(logsResult.stdout, logsResult.stderr).trimEnd() : "";
			const output = [
				formatRun(run, ref.repo, ref.runId, ref.jobId),
				logsResult
					? `Failed logs command: ${logsCommand}\nFailed logs exit code: ${logsResult.code}\n\n${logsOutput || "No failed logs output."}`
					: undefined,
			]
				.filter(Boolean)
				.join("\n\n");
			const durationMs = statusResult.durationMs + (logsResult?.durationMs ?? 0);
			const prefix = [
				`Status command: ${statusCommand}`,
				logsCommand ? `Logs command: ${logsCommand}` : undefined,
				`Status exit code: ${statusResult.code}`,
				logsResult ? `Logs exit code: ${logsResult.code}` : undefined,
				`Duration: ${formatDuration(durationMs)}`,
				statusResult.killed || logsResult?.killed ? "Process was killed (timeout or cancellation)." : undefined,
			]
				.filter(Boolean)
				.join("\n");
			const formatted = await formatCommandOutput(output, prefix);

			return {
				content: [{ type: "text", text: formatted.text }],
				details: {
					tool: "gh_run_inspect",
					repo: ref.repo,
					runId: ref.runId,
					jobId: ref.jobId,
					includeLogs,
					statusArgs,
					logsArgs,
					statusExitCode: statusResult.code,
					logsExitCode: logsResult?.code,
					statusDurationMs: statusResult.durationMs,
					logsDurationMs: logsResult?.durationMs,
					run,
					...formatted.details,
				},
			};
		},
	});
}

async function resolveRunRef(
	pi: ExtensionAPI,
	params: GhRunInspectInput,
	cwd: string,
	signal?: AbortSignal,
): Promise<{ repo: string; runId: number; jobId?: number }> {
	if (params.url !== undefined) {
		if (params.repo !== undefined || params.run_id !== undefined || params.job_id !== undefined) {
			throw new Error("When url is provided, do not also pass repo/run_id/job_id.");
		}
		return parseActionsRunUrl(params.url);
	}

	const repo = validateGithubRepo(params.repo) ?? (await requireCurrentGitHubRepo(pi, cwd, signal));
	const runId = requirePositiveSafeInteger(params.run_id, "run_id");
	const jobId = validatePositiveSafeInteger(params.job_id, "job_id");
	return { repo, runId, jobId };
}

function formatRunCommandPrefix(command: string, exitCode: number, durationMs: number, killed: boolean): string {
	return [
		`Command: ${command}`,
		`Exit code: ${exitCode}`,
		"Status: failed",
		`Duration: ${formatDuration(durationMs)}`,
		killed ? "Process was killed (timeout or cancellation)." : undefined,
	]
		.filter(Boolean)
		.join("\n");
}

function formatRun(run: RunPayload, repo: string, runId: number, jobId: number | undefined): string {
	const lines = [
		`Repo: ${repo}`,
		`Run: ${runId}`,
		jobId ? `Job: ${jobId}` : undefined,
		run.workflowName ? `Workflow: ${run.workflowName}` : undefined,
		run.name ? `Name: ${run.name}` : undefined,
		`Status: ${run.status ?? "unknown"}`,
		`Conclusion: ${run.conclusion ?? "unknown"}`,
		run.attempt !== undefined ? `Attempt: ${run.attempt}` : undefined,
		run.event ? `Event: ${run.event}` : undefined,
		run.headBranch ? `Branch: ${run.headBranch}` : undefined,
		run.headSha ? `SHA: ${run.headSha}` : undefined,
		run.createdAt ? `Created: ${run.createdAt}` : undefined,
		run.updatedAt ? `Updated: ${run.updatedAt}` : undefined,
		run.url ? `URL: ${run.url}` : undefined,
	]
		.filter(Boolean) as string[];

	const jobs = run.jobs ?? [];
	lines.push("", `Jobs: ${jobs.length}`);
	for (const job of jobs) {
		lines.push(`- ${job.name ?? job.databaseId ?? "unknown"}: status=${job.status ?? "unknown"}, conclusion=${job.conclusion ?? "unknown"}`);
		if (job.url) lines.push(`  ${job.url}`);
	}

	return lines.join("\n");
}
