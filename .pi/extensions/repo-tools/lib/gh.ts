import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { execRepoCommand, type SafeExecResult } from "./exec.ts";
import { mergeOutput } from "./output.ts";

export async function runGh(
	pi: ExtensionAPI,
	args: string[],
	options: { cwd: string; timeoutMs: number; signal?: AbortSignal },
): Promise<SafeExecResult> {
	return execRepoCommand(pi, "gh", args, options);
}

export function parseGhJson<T>(result: SafeExecResult, commandLabel: string): T {
	try {
		return JSON.parse(result.stdout) as T;
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(`${commandLabel} returned invalid JSON: ${message}`);
	}
}

export async function requireCurrentGitHubRepo(pi: ExtensionAPI, cwd: string, signal?: AbortSignal): Promise<string> {
	const result = await runGh(pi, ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], {
		cwd,
		signal,
		timeoutMs: 30_000,
	});
	if (result.code !== 0) {
		throw new Error(`Could not determine GitHub repo: ${mergeOutput(result.stdout, result.stderr).trim()}`);
	}

	const repo = result.stdout.trim();
	if (!repo) throw new Error("Could not determine GitHub repo.");
	return repo;
}
