import { formatComments, issueBody, labelSet } from "./issues.ts";
import type { Issue, PrdRunMetadata, SlicePlan } from "./types.ts";

export const AGENT_PROGRESS_INSTRUCTIONS = `- Send agent_update before each major phase, before running tests, and after test results.
- Send agent_update for blockers, important decisions, and completion summaries.
- Use agent_question when you need the human/coordinator to choose or unblock you; then stop and wait for a reply.
- Keep human updates under 160 chars when possible; never include secrets or full command output.`;

export function prdMetadata(repo: string, prd: Issue, plan: SlicePlan): PrdRunMetadata {
	return {
		repo,
		number: prd.number,
		title: prd.title,
		url: prd.url,
		context: formatPrdContext(repo, prd, plan),
		orderedSlices: plan.ordered.map((slice) => ({
			number: slice.number,
			title: slice.title,
			url: slice.url,
			blockers: plan.blockersBySlice.get(slice.number) ?? [],
		})),
		skippedSlices: plan.skipped.map((skipped) => ({
			number: skipped.issue.number,
			title: skipped.issue.title,
			url: skipped.issue.url,
			reason: skipped.reason,
		})),
	};
}

export function formatPrdContext(repo: string, prd: Issue, plan: SlicePlan): string {
	return `## Parent PRD

Repo: ${repo}
Issue: #${prd.number} ${prd.title}
URL: ${prd.url ?? "unknown"}
Labels: ${[...labelSet(prd)].join(", ") || "none"}

${issueBody(prd)}

## PRD Comments

${formatComments(prd)}

## Ordered ready slices

${plan.ordered
		.map((slice, index) => {
			const blockers = plan.blockersBySlice.get(slice.number) ?? [];
			return `### ${index + 1}. #${slice.number} ${slice.title}
URL: ${slice.url ?? "unknown"}
Blocked by: ${blockers.length ? blockers.map((number) => `#${number}`).join(", ") : "none"}

${issueBody(slice)}

Comments:
${formatComments(slice)}`;
		})
		.join("\n\n---\n\n")}

## Skipped slices

${plan.skipped.length ? plan.skipped.map((skipped) => `- #${skipped.issue.number} ${skipped.issue.title}: ${skipped.reason}`).join("\n") : "None"}`;
}

export function buildPrdImplementerPrompt(repo: string, prd: Issue, plan: SlicePlan): string {
	const firstSlice = plan.ordered[0];
	return `You are implementing a Memorable PRD run, based on .sandcastle/implement-prd.ts.

${formatPrdContext(repo, prd, plan)}

## Required process

- Treat the ordered ready slices as the source of truth. Do not implement the parent PRD as one blob.
- AgentRoom assigns one current slice at a time. Start with #${firstSlice.number} ${firstSlice.title}.
- Implement only the assigned current slice; never start a later slice on your own.
- Before coding, check worktree status/base. If the diff is polluted or base is wrong, use agent_question and wait.
- For the assigned slice, follow the required tdd skill: one behavior test → failing RED run → minimal GREEN implementation → passing run → repeat/refactor.
- A test that passes before its implementation exists is a defect: confirm RED first. Assert lifecycle/temporal behavior through the resolved read path (current truth, point-in-time, history), never by fetching a specific version by id. A supersession test asserts on what the read path returns after supersession, not on the predecessor.
- When the assigned slice is ready, call agent_submit_review with the changed files and structured verification (command, newTests, implFiles). AgentRoom reverts your implFiles and reruns the command — the tests must fail without the implementation — so declare them accurately; then stop.
- Do not continue because the reviewer is quiet. Wait for AgentRoom to commit, compact, and send the next slice assignment.
- Do not anticipate or implement future slices. But reading the existing code this slice touches — validation paths, public parameter names, invariants, and the read paths that resolve what you write — is required, not scope creep; new code paths must converge on the same validation gate their siblings enforce.
- Do not commit. AgentRoom commits approved slices after reviewer approval.
- If you touch Memorable product model or domain language, read docs/product.md, docs/ubiquitous-language.md, and relevant ADRs first.
- Use uv for Python tasks.

## Current slice assignment

#${firstSlice.number} ${firstSlice.title}

## Human-visible progress

${AGENT_PROGRESS_INSTRUCTIONS}`;
}

export function buildPrdReviewerPrompt(repo: string, prd: Issue, plan: SlicePlan): string {
	return `You are the persistent reviewer for a slice-based Memorable PRD run.

${formatPrdContext(repo, prd, plan)}

## Review process

- Wait for implementer review requests.
- Review only; do not modify files or commit.
- Review the current diff against the run base, focused on the requested slice.
- Report blocking vs non-blocking findings with exact paths/lines when possible.
- When review is complete, call agent_finish_review exactly once:
  - status=changes_requested when blockers remain; include actionable findings.
  - status=approved only when there are no blocking findings.
- Do not use agent_send as the final review verdict; AgentRoom needs agent_finish_review to gate the next slice.
- Use agent_update for review start/completion and blocking findings visible to the human.

## Human-visible progress

${AGENT_PROGRESS_INSTRUCTIONS}`;
}

export function buildPrdArchitectPrompt(repo: string, prd: Issue, plan: SlicePlan): string {
	return `You are the persistent architect for a slice-based Memorable PRD run.

${formatPrdContext(repo, prd, plan)}

## Architecture process

- Immediately review the PRD and ordered slices for product/domain/architecture constraints.
- Broadcast constraints or blockers relevant to all agents with agent_broadcast, using kind "architecture-constraint". AgentRoom persists these and re-injects them into every slice assignment, so state cross-slice invariants once, up front, as crisp rules.
- Review final branch/diff when AgentRoom asks after all slices are approved and committed.
- For final branch review, call agent_finish_architecture_review exactly once so AgentRoom can publish the PR.
- Review only; do not modify files or commit.
- Use agent_update for architecture start/completion and blocking risks visible to the human.

## Human-visible progress

${AGENT_PROGRESS_INSTRUCTIONS}`;
}
