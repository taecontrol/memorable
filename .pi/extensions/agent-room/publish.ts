import fs from "node:fs/promises";
import path from "node:path";

import { execFile, ghJson, git } from "./github.ts";
import { nowIso } from "./storage.ts";
import type { AgentRoom, GhPullRequest, PrdRunMetadata, PrdSliceMetadata, PullRequestMetadata } from "./types.ts";

export async function publishPrdPullRequest(room: AgentRoom): Promise<PullRequestMetadata> {
	const prd = room.manifest.prd;
	if (!prd) throw new Error("No PRD metadata available for PR publication.");
	const status = (await git(room.cwd, ["status", "--porcelain"])).stdout.trim();
	if (status) throw new Error(`Cannot publish PR with dirty worktree:\n${status}`);

	const branch = room.manifest.worktree?.branch ?? (await git(room.cwd, ["branch", "--show-current"])).stdout.trim();
	if (!branch) throw new Error("Cannot determine current branch for PR publication.");
	const base = baseBranchName(room.manifest.worktree?.baseRef);
	const title = `Implement #${prd.number}: ${prd.title}`;
	const body = await buildPrdPullRequestBody(room);
	const bodyFile = path.join(room.runDir, "pull-request.md");
	await fs.writeFile(bodyFile, body, "utf8");

	await git(room.cwd, ["push", "-u", "origin", branch]);
	const priorPrUrl = room.manifest.pullRequest?.url;
	let createdPullRequest = false;
	let pullRequest = await findPullRequestForBranch(room.cwd, prd.repo, branch);
	if (pullRequest) {
		await execFile("gh", ["pr", "edit", String(pullRequest.number), "-R", prd.repo, "--title", title, "--body-file", bodyFile], {
			cwd: room.cwd,
			maxBuffer: 10 * 1024 * 1024,
		});
		if (pullRequest.isDraft) {
			await execFile("gh", ["pr", "ready", String(pullRequest.number), "-R", prd.repo], { cwd: room.cwd, maxBuffer: 1024 * 1024 });
		}
		pullRequest = await viewPullRequest(room.cwd, prd.repo, pullRequest.number);
	} else {
		await execFile("gh", ["pr", "create", "-R", prd.repo, "--base", base, "--title", title, "--body-file", bodyFile], {
			cwd: room.cwd,
			maxBuffer: 10 * 1024 * 1024,
		});
		createdPullRequest = true;
		pullRequest = await findPullRequestForBranch(room.cwd, prd.repo, branch);
		if (!pullRequest) throw new Error("PR was created but could not be found by branch.");
	}

	if (createdPullRequest || (priorPrUrl && priorPrUrl !== pullRequest.url)) await commentOnPrdIssue(room, pullRequest);
	return { number: pullRequest.number, url: pullRequest.url, title: pullRequest.title, createdAt: nowIso() };
}

export function baseBranchName(baseRef: string | undefined): string {
	const normalized = (baseRef ?? "origin/main").replace(/^refs\/heads\//, "").replace(/^remotes\/origin\//, "").replace(/^origin\//, "");
	return normalized && normalized !== "HEAD" ? normalized : "main";
}

export async function findPullRequestForBranch(cwd: string, repo: string, branch: string): Promise<GhPullRequest | undefined> {
	const prs = await ghJson<GhPullRequest[]>(cwd, [
		"pr",
		"list",
		"-R",
		repo,
		"--state",
		"open",
		"--head",
		branch,
		"--json",
		"number,url,title,isDraft",
		"--limit",
		"1",
	]);
	return prs[0];
}

export async function viewPullRequest(cwd: string, repo: string, number: number): Promise<GhPullRequest> {
	return ghJson<GhPullRequest>(cwd, ["pr", "view", String(number), "-R", repo, "--json", "number,url,title,isDraft"]);
}

export async function buildPrdPullRequestBody(room: AgentRoom): Promise<string> {
	const prd = room.manifest.prd;
	if (!prd) throw new Error("No PRD metadata available for PR body.");
	const finalReview = room.manifest.finalArchitectureReview;
	const prdKeyword = prd.skippedSlices.length === 0 ? "Closes" : "Refs";
	const completedRows = await Promise.all(
		prd.orderedSlices.map(async (slice) => {
			const sha = await sliceCommitSha(room, prd, slice.number);
			return completedSliceRow(slice, sha);
		}),
	);
	const skippedRows = prd.skippedSlices.map((slice) => `- #${slice.number} - ${slice.title}: ${slice.reason}`);

	return `## PRD

${prdKeyword} #${prd.number}

## Completed Slices

${completedRows.join("\n") || "None"}

## Skipped Slices

${skippedRows.join("\n") || "None"}

## Verification

${finalReview?.verification ?? "See AgentRoom review messages. Each slice was reviewed before commit."}

## Architect Review

Status: ${finalReview?.status ?? "approved"}

${finalReview?.findings ?? "No findings."}

## AgentRoom

Run: ${room.id}
Branch: ${room.manifest.worktree?.branch ?? "current branch"}
`;
}

function completedSliceRow(slice: PrdSliceMetadata, sha: string | undefined): string {
	const suffix = sha ? ` (${sha.slice(0, 12)})` : "";
	if (slice.synthetic === "final-architecture-fix") return `- Final architecture fix: ${slice.title}${suffix}`;
	return `- Closes #${slice.number} - ${slice.title}${suffix}`;
}

function issueSliceReference(slice: PrdSliceMetadata): string | undefined {
	return slice.synthetic === "final-architecture-fix" ? undefined : `#${slice.number}`;
}

export async function sliceCommitSha(room: AgentRoom, prd: PrdRunMetadata, sliceNumber: number): Promise<string | undefined> {
	const result = await git(room.cwd, ["log", "--format=%H", "--fixed-strings", "--grep", `Implement PRD #${prd.number} slice #${sliceNumber}`, "-1"]);
	return result.stdout.trim().split("\n").find(Boolean);
}

export async function commentOnPrdIssue(room: AgentRoom, pullRequest: GhPullRequest): Promise<void> {
	const prd = room.manifest.prd;
	if (!prd) return;
	const implemented = prd.orderedSlices.map(issueSliceReference).filter((value): value is string => Boolean(value)).join(", ");
	const skipped = prd.skippedSlices.map((slice) => `#${slice.number}`).join(", ") || "none";
	const body = `Opened PR ${pullRequest.url} implementing ${implemented || "none"}. Skipped: ${skipped}.`;
	const bodyFile = path.join(room.runDir, "prd-comment.md");
	await fs.writeFile(bodyFile, body, "utf8");
	await execFile("gh", ["issue", "comment", String(prd.number), "-R", prd.repo, "--body-file", bodyFile], {
		cwd: room.cwd,
		maxBuffer: 1024 * 1024,
	});
}
