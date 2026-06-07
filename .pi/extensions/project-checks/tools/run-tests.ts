import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { execProjectCommand, formatDuration } from "../lib/exec.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import {
	validateKeywordExpression,
	validateMarkerExpression,
	validateMaxfail,
	validateTestTargets,
	validateTimeoutSeconds,
} from "../lib/validation.ts";

const RunTestsParams = Type.Object({
	targets: Type.Optional(
		Type.Array(Type.String({ description: "Pytest target under tests/, optionally with :: node id." }), {
			description: "Test files or node IDs under tests/. Empty or omitted runs the whole suite.",
			maxItems: 20,
		}),
	),
	marker: Type.Optional(
		Type.String({ description: "Pytest marker expression. Only the project marker 'integration' is allowed." }),
	),
	keyword: Type.Optional(
		Type.String({ description: "Pytest -k expression using identifiers, and/or/not, and parentheses." }),
	),
	maxfail: Type.Optional(Type.Integer({ description: "Stop after this many failures. Range: 1..50.", minimum: 1, maximum: 50 })),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600.", minimum: 5, maximum: 600 }),
	),
});

type RunTestsInput = Static<typeof RunTestsParams>;

export function createRunTestsTool(pi: ExtensionAPI) {
	return defineTool({
		name: "run_tests",
		label: "Run Tests",
		description:
			"Run project tests through the fixed command `uv run --extra dev pytest -q --color=no`. Accepts only validated pytest targets under tests/, marker/keyword expressions, maxfail, and timeout. Output is truncated to built-in limits; full output is saved to a temp file when truncated.",
		promptSnippet: "Run Memorable's pytest suite safely without using bash.",
		promptGuidelines: [
			"Use run_tests instead of bash for pytest. Do not ask for raw pytest arguments; pass only targets, marker, keyword, maxfail, and timeout_seconds.",
			"Use run_tests targets only for paths or node IDs under tests/. Omit targets for the full suite.",
		],
		parameters: RunTestsParams,

		async execute(_toolCallId, params: RunTestsInput, signal, onUpdate, ctx) {
			const targets = validateTestTargets(ctx.cwd, params.targets);
			const marker = validateMarkerExpression(params.marker);
			const keyword = validateKeywordExpression(params.keyword);
			const maxfail = validateMaxfail(params.maxfail);
			const defaultTimeoutSeconds = targets.length === 0 ? 300 : 120;
			const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, defaultTimeoutSeconds);

			const args = ["run", "--extra", "dev", "pytest", "-q", "--color=no"];
			if (maxfail !== undefined) args.push(`--maxfail=${maxfail}`);
			if (marker !== undefined) args.push("-m", marker);
			if (keyword !== undefined) args.push("-k", keyword);
			args.push(...targets);

			const displayCommand = formatArgv("uv", args);
			onUpdate?.({ content: [{ type: "text", text: `Running ${displayCommand}` }], details: {} });

			const result = await execProjectCommand(pi, "uv", args, {
				cwd: ctx.cwd,
				signal,
				timeoutMs: timeoutSeconds * 1000,
			});

			const passed = result.code === 0;
			const output = mergeOutput(result.stdout, result.stderr);
			const prefix = [
				`Command: ${displayCommand}`,
				`Exit code: ${result.code}`,
				`Status: ${passed ? "passed" : "failed"}`,
				`Duration: ${formatDuration(result.durationMs)}`,
				result.killed ? "Process was killed (timeout or cancellation)." : undefined,
			]
				.filter(Boolean)
				.join("\n");
			const formatted = await formatCommandOutput(output, prefix);

			return {
				content: [{ type: "text", text: formatted.text }],
				details: {
					tool: "run_tests",
					command: "uv",
					args,
					targets,
					marker,
					keyword,
					maxfail,
					timeoutSeconds,
					exitCode: result.code,
					passed,
					killed: result.killed,
					durationMs: result.durationMs,
					...formatted.details,
				},
			};
		},
	});
}
