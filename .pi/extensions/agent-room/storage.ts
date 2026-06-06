import fs from "node:fs/promises";
import path from "node:path";

import type { RoomMessage } from "./types.ts";

const RUNS_DIR = [".pi", "agent-room", "runs"];

export function nowIso(): string {
	return new Date().toISOString();
}

export function runsRoot(cwd: string): string {
	return path.join(cwd, ...RUNS_DIR);
}

export function runDir(cwd: string, runId: string): string {
	return path.join(runsRoot(cwd), runId);
}

export function manifestPath(runDirPath: string): string {
	return path.join(runDirPath, "manifest.json");
}

export function mailboxPath(runDirPath: string): string {
	return path.join(runDirPath, "mailbox.jsonl");
}

export async function ensureDir(dir: string): Promise<void> {
	await fs.mkdir(dir, { recursive: true });
}

export async function readJson<T>(filePath: string): Promise<T | undefined> {
	try {
		return JSON.parse(await fs.readFile(filePath, "utf8")) as T;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
		throw error;
	}
}

export async function writeJson(filePath: string, value: unknown): Promise<void> {
	await ensureDir(path.dirname(filePath));
	await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export async function appendJsonl(filePath: string, value: unknown): Promise<void> {
	await ensureDir(path.dirname(filePath));
	await fs.appendFile(filePath, `${JSON.stringify(value)}\n`, "utf8");
}

export async function readMailbox(filePath: string): Promise<RoomMessage[]> {
	try {
		const content = await fs.readFile(filePath, "utf8");
		return content
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter(Boolean)
			.map((line) => JSON.parse(line) as RoomMessage);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
		throw error;
	}
}
