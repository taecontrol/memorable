import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type, type Static } from "typebox";

import { formatDuration } from "../lib/exec.ts";
import { runGit } from "../lib/git.ts";
import { applyLineWindow, formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import {
	validateCount,
	validateLineLimit,
	validateLineOffset,
	validateRepoPaths,
	validateTimeoutSeconds,
} from "../lib/validation.ts";

const GitInspectParams = Type.Object({
	mode: StringEnum(["status", "diff", "log", "info"] as const, {
		description: "Inspection mode: status, diff, log, or info.",
	}),
	branch: Type.Optional(Type.Boolean({ description: "For mode=status, include branch information (`git status --short --branch`)." })),
	paths: Type.Optional(
		Type.Array(Type.String({ description: "Repo-relative path filter for mode=diff." }), {
			description: "Repo-relative path filters for mode=diff. Max 50. No absolute paths, '..', ':' or pathspec magic.",
			maxItems: 50,
		}),
	),
	staged: Type.Optional(Type.Boolean({ description: "For mode=diff, inspect staged changes (`--staged`). Defaults to false." })),
	stat: Type.Optional(Type.Boolean({ description: "For mode=diff, show diff stat (`--stat`). Mutually exclusive with check/nameOnly." })),
	check: Type.Optional(Type.Boolean({ description: "For mode=diff, check whitespace/errors (`--check`). Mutually exclusive with stat/nameOnly." })),
	nameOnly: Type.Optional(Type.Boolean({ description: "For mode=diff, show changed file names only (`--name-only`). Mutually exclusive with stat/check." })),
	count: Type.Optional(Type.Integer({ description: "For mode=log, commit count. Range: 1..50. Defaults to 5.", minimum: 1, maximum: 50 })),
	decorate: Type.Optional(Type.Boolean({ description: "For mode=log, include refs with `--decorate`." })),
	offset: Type.Optional(Type.Integer({ description: "1-indexed output line offset. Useful for paging large diffs.", minimum: 1 })),
	limit: Type.Optional(Type.Integer({ description: "Maximum output lines to return from offset. Range: 1..2000.", minimum: 1, maximum: 2000 })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600. Defaults to 60.", minimum: 5, maximum: 600 }),
	),
});

type GitInspectInput = Static<typeof GitInspectParams>;

export function createGitInspectTool(pi: ExtensionAPI) {
	return defineTool({
		name: "git_inspect",
		label: "Git Inspect",
		description:
			"Inspect the current git repository without bash. Supports status, diff, log, and repo info. Diff output supports validated path filters and offset/limit paging; output is truncated to built-in limits with full output saved when truncated.",
		promptSnippet: "Inspect git status, diffs, logs, and branch/repo info safely without bash.",
		promptGuidelines: [
			"Use git_inspect instead of bash for git status, git diff, git diff --stat/--check/--name-only, git log --oneline, and branch/repo info.",
			"Use git_inspect mode=diff with offset/limit instead of piping git diff through sed for pagination.",
		],
		parameters: GitInspectParams,

		async execute(_toolCallId, params: GitInspectInput, signal, onUpdate, ctx) {
			const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 60);
			const offset = validateLineOffset(params.offset);
			const limit = validateLineLimit(params.limit);

			if (params.mode === "info") {
				return inspectInfo(pi, ctx.cwd, timeoutSeconds, signal);
			}

			const args = buildGitArgs(ctx.cwd, params);
			const displayCommand = formatArgv("git", args);
			onUpdate?.({ content: [{ type: "text", text: `Running ${displayCommand}` }], details: {} });

			const result = await runGit(pi, args, {
				cwd: ctx.cwd,
				signal,
				timeoutMs: timeoutSeconds * 1000,
			});

			const rawOutput = mergeOutput(result.stdout, result.stderr);
			const lineWindow = applyLineWindow(rawOutput, offset, limit);
			const prefix = [
				`Command: ${displayCommand}`,
				`Exit code: ${result.code}`,
				`Status: ${result.code === 0 ? "ok" : "failed"}`,
				`Duration: ${formatDuration(result.durationMs)}`,
				lineWindow.details
					? `Line window: ${lineWindow.details.startLine}-${lineWindow.details.endLine} of ${lineWindow.details.totalLines}`
					: undefined,
				result.killed ? "Process was killed (timeout or cancellation)." : undefined,
			]
				.filter(Boolean)
				.join("\n");
			const formatted = await formatCommandOutput(lineWindow.output, prefix);

			return {
				content: [{ type: "text", text: formatted.text }],
				details: {
					tool: "git_inspect",
					mode: params.mode,
					command: "git",
					args,
					exitCode: result.code,
					killed: result.killed,
					durationMs: result.durationMs,
					lineWindow: lineWindow.details,
					...formatted.details,
				},
			};
		},
	});
}

function buildGitArgs(cwd: string, params: GitInspectInput): string[] {
	if (params.mode !== "diff" && params.paths !== undefined) throw new Error("paths is only valid with mode=diff.");
	if (params.mode !== "diff" && (params.staged || params.stat || params.check || params.nameOnly)) {
		throw new Error("staged/stat/check/nameOnly are only valid with mode=diff.");
	}
	if (params.mode !== "status" && params.branch !== undefined) throw new Error("branch is only valid with mode=status.");
	if (params.mode !== "log" && (params.count !== undefined || params.decorate !== undefined)) {
		throw new Error("count/decorate are only valid with mode=log.");
	}

	if (params.mode === "status") {
		const args = ["status", "--short"];
		if (params.branch) args.push("--branch");
		return args;
	}

	if (params.mode === "log") {
		const count = validateCount(params.count, 5, 50, "count");
		const args = ["log", "--oneline"];
		if (params.decorate) args.push("--decorate");
		args.push(`-${count}`);
		return args;
	}

	const selectedFormats = [params.stat, params.check, params.nameOnly].filter(Boolean).length;
	if (selectedFormats > 1) throw new Error("stat, check, and nameOnly are mutually exclusive.");

	const paths = validateRepoPaths(cwd, params.paths);
	const args = ["diff"];
	if (params.staged) args.push("--staged");
	if (params.stat) args.push("--stat");
	if (params.check) args.push("--check");
	if (params.nameOnly) args.push("--name-only");
	if (paths.length > 0) args.push("--", ...paths);
	return args;
}

async function inspectInfo(pi: ExtensionAPI, cwd: string, timeoutSeconds: number, signal?: AbortSignal) {
	const commands = [
		{ label: "current_branch", args: ["branch", "--show-current"] },
		{ label: "abbrev_ref", args: ["rev-parse", "--abbrev-ref", "HEAD"] },
		{ label: "repo_root", args: ["rev-parse", "--show-toplevel"] },
		{ label: "head", args: ["rev-parse", "HEAD"] },
	];

	const results = [];
	for (const command of commands) {
		const result = await runGit(pi, command.args, { cwd, signal, timeoutMs: timeoutSeconds * 1000 });
		results.push({ ...command, result });
	}

	const totalDurationMs = results.reduce((total, item) => total + item.result.durationMs, 0);
	const output = results
		.map((item) => {
			const value = mergeOutput(item.result.stdout, item.result.stderr).trim() || "<empty>";
			return `${item.label}: ${value}\n  command: ${formatArgv("git", item.args)}\n  exitCode: ${item.result.code}`;
		})
		.join("\n");
	const allOk = results.every((item) => item.result.code === 0);
	const prefix = [
		"Commands: git branch --show-current; git rev-parse --abbrev-ref HEAD; git rev-parse --show-toplevel; git rev-parse HEAD",
		`Status: ${allOk ? "ok" : "failed"}`,
		`Duration: ${formatDuration(totalDurationMs)}`,
	]
		.filter(Boolean)
		.join("\n");
	const formatted = await formatCommandOutput(output, prefix);

	return {
		content: [{ type: "text" as const, text: formatted.text }],
		details: {
			tool: "git_inspect",
			mode: "info",
			results: results.map((item) => ({
				label: item.label,
				args: item.args,
				exitCode: item.result.code,
				killed: item.result.killed,
				durationMs: item.result.durationMs,
			})),
			durationMs: totalDurationMs,
			...formatted.details,
		},
	};
}
