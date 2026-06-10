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

export interface LineWindowResult {
	output: string;
	details?: {
		startLine: number;
		endLine: number;
		totalLines: number;
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
		const tempDir = await mkdtemp(path.join(tmpdir(), "pi-repo-tools-"));
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

export function applyLineWindow(output: string, offset: number | undefined, limit: number | undefined): LineWindowResult {
	if (offset === undefined && limit === undefined) return { output };

	const startLine = offset ?? 1;
	const lines = output.split(/\r?\n/);
	const totalLines = lines.length;
	const startIndex = Math.max(startLine - 1, 0);
	const endIndex = limit === undefined ? totalLines : Math.min(startIndex + limit, totalLines);
	const selected = lines.slice(startIndex, endIndex).join("\n");

	return {
		output: selected,
		details: {
			startLine,
			endLine: endIndex,
			totalLines,
		},
	};
}

function quoteArgForDisplay(arg: string): string {
	if (/^[A-Za-z0-9_./:=\-]+$/.test(arg)) return arg;
	return JSON.stringify(arg);
}
