import { validateGithubRepo } from "./validation.ts";

export interface IssueRef {
	repo: string;
	number: number;
}

export interface ActionsRunRef {
	repo: string;
	runId: number;
	jobId?: number;
}

export function parseIssueInput(input: string, defaultRepo: string): IssueRef {
	const trimmed = input.trim();
	const urlMatch = /^https?:\/\/github\.com\/([^/]+\/[^/]+)\/issues\/(\d+)/.exec(trimmed);
	if (urlMatch) return { repo: requireRepo(urlMatch[1]), number: requireSafeId(urlMatch[2], "issue number") };

	const repoIssueMatch = /^([^\s/#]+\/[^\s#]+)#(\d+)$/.exec(trimmed);
	if (repoIssueMatch) return { repo: requireRepo(repoIssueMatch[1]), number: requireSafeId(repoIssueMatch[2], "issue number") };

	const numberMatch = /^#?(\d+)$/.exec(trimmed);
	if (numberMatch) return { repo: defaultRepo, number: requireSafeId(numberMatch[1], "issue number") };

	throw new Error(`Could not parse GitHub issue reference: ${input}`);
}

export function parseActionsRunUrl(input: string): ActionsRunRef {
	let url: URL;
	try {
		url = new URL(input.trim());
	} catch {
		throw new Error(`Invalid GitHub Actions URL: ${input}`);
	}

	if (url.hostname !== "github.com") throw new Error("Actions URL must be on github.com.");

	const parts = url.pathname.split("/").filter(Boolean);
	if (parts.length < 5 || parts[2] !== "actions" || parts[3] !== "runs") {
		throw new Error("Actions URL must look like https://github.com/owner/repo/actions/runs/<run-id>[/job/<job-id>].");
	}

	const repo = requireRepo(`${parts[0]}/${parts[1]}`);
	const runId = requireSafeId(parts[4], "run_id");
	let jobId: number | undefined;

	const jobIndex = parts.indexOf("job", 5);
	if (jobIndex >= 0) {
		const rawJobId = parts[jobIndex + 1];
		if (!rawJobId) throw new Error("Actions URL contains /job/ without a job id.");
		jobId = requireSafeId(rawJobId, "job_id");
	}

	return { repo, runId, jobId };
}

function requireRepo(value: string): string {
	const repo = validateGithubRepo(value);
	if (!repo) throw new Error("repo is required.");
	return repo;
}

function requireSafeId(raw: string, label: string): number {
	if (!/^\d+$/.test(raw)) throw new Error(`${label} must be numeric.`);
	const value = Number(raw);
	if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${label} must be a positive safe integer.`);
	return value;
}
