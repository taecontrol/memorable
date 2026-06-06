import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";

import type { Issue, IssueRef } from "./types.ts";

export const execFile = promisify(execFileCallback);

export async function git(cwd: string, args: string[]): Promise<{ stdout: string; stderr: string }> {
	const result = await execFile("git", args, { cwd, maxBuffer: 10 * 1024 * 1024 });
	return { stdout: String(result.stdout), stderr: String(result.stderr) };
}

export async function ghJson<T>(cwd: string, args: string[]): Promise<T> {
	const result = await execFile("gh", args, { cwd, maxBuffer: 20 * 1024 * 1024 });
	return JSON.parse(String(result.stdout)) as T;
}

export async function currentGitHubRepo(cwd: string): Promise<string> {
	const result = await execFile("gh", ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], {
		cwd,
		maxBuffer: 1024 * 1024,
	});
	return String(result.stdout).trim();
}

export function parseIssueInput(input: string, defaultRepo: string): IssueRef {
	const trimmed = input.trim();
	const urlMatch = /^https?:\/\/github\.com\/([^/]+\/[^/]+)\/issues\/(\d+)/.exec(trimmed);
	if (urlMatch) return { repo: urlMatch[1], number: Number(urlMatch[2]) };

	const repoIssueMatch = /^([^\s/#]+\/[^\s#]+)#(\d+)$/.exec(trimmed);
	if (repoIssueMatch) return { repo: repoIssueMatch[1], number: Number(repoIssueMatch[2]) };

	const numberMatch = /^#?(\d+)$/.exec(trimmed);
	if (numberMatch) return { repo: defaultRepo, number: Number(numberMatch[1]) };

	throw new Error(`Could not parse PRD issue reference: ${input}`);
}

export async function fetchIssue(repo: string, number: number, cwd: string): Promise<Issue> {
	return ghJson<Issue>(cwd, [
		"issue",
		"view",
		String(number),
		"-R",
		repo,
		"--comments",
		"--json",
		"number,title,body,labels,state,comments,url",
	]);
}

export async function fetchIssueOptional(repo: string, number: number, cwd: string): Promise<Issue | undefined> {
	try {
		return await fetchIssue(repo, number, cwd);
	} catch {
		return undefined;
	}
}
