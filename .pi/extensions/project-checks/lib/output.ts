import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	formatSize,
	truncateTail,
	type TruncationResult,
} from "@earendil-works/pi-coding-agent";

export interface FormattedOutput {
	text: string;
	details: {
		truncated: boolean;
		fullOutputPath?: string;
		truncation?: TruncationResult;
	};
}

export async function formatCommandOutput(output: string, prefix: string): Promise<FormattedOutput> {
	const normalizedOutput = output.trimEnd();
	const truncation = truncateTail(normalizedOutput || "No output.", {
		maxLines: DEFAULT_MAX_LINES,
		maxBytes: DEFAULT_MAX_BYTES,
	});

	let text = `${prefix}\n\n${truncation.content}`;
	const details: FormattedOutput["details"] = { truncated: truncation.truncated };

	if (truncation.truncated) {
		const tempDir = await mkdtemp(path.join(tmpdir(), "pi-project-checks-"));
		const tempFile = path.join(tempDir, "output.txt");
		await writeFile(tempFile, normalizedOutput, "utf8");

		details.fullOutputPath = tempFile;
		details.truncation = truncation;

		const omittedLines = truncation.totalLines - truncation.outputLines;
		const omittedBytes = truncation.totalBytes - truncation.outputBytes;
		text += `\n\n[Output truncated: showing last ${truncation.outputLines} of ${truncation.totalLines} lines`;
		text += ` (${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}).`;
		text += ` ${omittedLines} lines (${formatSize(omittedBytes)}) omitted.`;
		text += ` Full output saved to: ${tempFile}]`;
	}

	return { text, details };
}

export function mergeOutput(stdout: string, stderr: string): string {
	if (stdout && stderr) return `${stdout}\n${stderr}`;
	return stdout || stderr;
}

export function formatArgv(command: string, args: string[]): string {
	return [command, ...args].map(quoteArgForDisplay).join(" ");
}

function quoteArgForDisplay(arg: string): string {
	if (/^[A-Za-z0-9_./:=\-]+$/.test(arg)) return arg;
	return JSON.stringify(arg);
}
