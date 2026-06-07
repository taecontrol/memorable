import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { execRepoCommand, type SafeExecResult } from "./exec.ts";
import { mergeOutput } from "./output.ts";

export async function runGit(
	pi: ExtensionAPI,
	args: string[],
	options: { cwd: string; timeoutMs: number; signal?: AbortSignal },
): Promise<SafeExecResult> {
	return execRepoCommand(pi, "git", args, options);
}

export async function requireCurrentBranch(pi: ExtensionAPI, cwd: string, signal?: AbortSignal): Promise<string> {
	const branchResult = await runGit(pi, ["branch", "--show-current"], { cwd, signal, timeoutMs: 15_000 });
	if (branchResult.code === 0) {
		const branch = branchResult.stdout.trim();
		if (branch) return branch;
	}

	const fallbackResult = await runGit(pi, ["rev-parse", "--abbrev-ref", "HEAD"], { cwd, signal, timeoutMs: 15_000 });
	if (fallbackResult.code !== 0) {
		throw new Error(`Could not determine current branch: ${mergeOutput(fallbackResult.stdout, fallbackResult.stderr).trim()}`);
	}

	const fallback = fallbackResult.stdout.trim();
	if (!fallback || fallback === "HEAD") throw new Error("Cannot determine current branch; repository may be in detached HEAD state.");
	return fallback;
}

export async function requireRepoRoot(pi: ExtensionAPI, cwd: string, signal?: AbortSignal): Promise<string> {
	const result = await runGit(pi, ["rev-parse", "--show-toplevel"], { cwd, signal, timeoutMs: 15_000 });
	if (result.code !== 0) {
		throw new Error(`Could not determine repository root: ${mergeOutput(result.stdout, result.stderr).trim()}`);
	}

	const root = result.stdout.trim();
	if (!root) throw new Error("Could not determine repository root.");
	return root;
}
