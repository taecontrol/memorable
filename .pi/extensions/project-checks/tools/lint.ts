import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";

import { execProjectCommand, formatDuration } from "../lib/exec.ts";
import { formatArgv, formatCommandOutput, mergeOutput } from "../lib/output.ts";
import { validateLintPaths, validateTimeoutSeconds } from "../lib/validation.ts";

const LintParams = Type.Object({
	paths: Type.Optional(
		Type.Array(Type.String({ description: "Project-relative Python path to lint." }), {
			description: "Lint paths. Omit to run ruff over the whole project. Allowed roots: ., src/, tests/, scripts/, pyproject.toml.",
			maxItems: 50,
		}),
	),
	fix: Type.Optional(
		Type.Boolean({ description: "Apply safe ruff fixes with --fix. This may mutate Python files." }),
	),
	timeout_seconds: Type.Optional(
		Type.Integer({ description: "Wall-clock timeout in seconds. Range: 5..600.", minimum: 5, maximum: 600 }),
	),
});

type LintInput = Static<typeof LintParams>;

export function createLintTool(pi: ExtensionAPI) {
	return defineTool({
		name: "lint",
		label: "Lint",
		description:
			"Run project linting through the fixed command `uv run --extra dev ruff check`. Accepts only validated project-relative paths, optional safe --fix, and timeout. Output is truncated to built-in limits; full output is saved to a temp file when truncated.",
		promptSnippet: "Run Memorable's ruff lint checks safely without using bash.",
		promptGuidelines: [
			"Use lint instead of bash for ruff check. Do not ask for raw ruff arguments; pass only paths, fix, and timeout_seconds.",
			"Use lint with fix=true only when you intend to let ruff mutate files; do not call it in parallel with edit/write tools.",
		],
		parameters: LintParams,

		async execute(_toolCallId, params: LintInput, signal, onUpdate, ctx) {
			const paths = validateLintPaths(ctx.cwd, params.paths);
			const fix = params.fix ?? false;
			const timeoutSeconds = validateTimeoutSeconds(params.timeout_seconds, 120);

			const args = ["run", "--extra", "dev", "ruff", "check"];
			if (fix) args.push("--fix");
			args.push(...paths);

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
					tool: "lint",
					command: "uv",
					args,
					paths,
					fix,
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
