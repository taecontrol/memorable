import type { ExecResult, ExtensionAPI } from "@earendil-works/pi-coding-agent";

export interface SafeExecResult extends ExecResult {
	durationMs: number;
}

export async function execRepoCommand(
	pi: ExtensionAPI,
	command: string,
	args: string[],
	options: { cwd: string; timeoutMs: number; signal?: AbortSignal },
): Promise<SafeExecResult> {
	const started = Date.now();
	const result = await pi.exec(command, args, {
		cwd: options.cwd,
		signal: options.signal,
		timeout: options.timeoutMs,
	});
	return { ...result, durationMs: Date.now() - started };
}

export function formatDuration(ms: number): string {
	if (ms < 1000) return `${ms}ms`;
	return `${(ms / 1000).toFixed(1)}s`;
}
