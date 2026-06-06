import {
	currentGitHubRepo,
	fetchIssue,
	fetchIssueOptional,
	ghJson,
	parseIssueInput,
} from "./github.ts";
import { extractBlockers, isChildOfPrd, issueBody, labelSet } from "./issues.ts";
import type { Issue, SkippedSlice, SlicePlan } from "./types.ts";

export async function loadPrdContext(cwd: string, input: string): Promise<{ repo: string; prd: Issue; plan: SlicePlan }> {
	const defaultRepo = await currentGitHubRepo(cwd);
	const issueRef = parseIssueInput(input, defaultRepo);
	const prd = await fetchIssue(issueRef.repo, issueRef.number, cwd);
	const plan = await buildSlicePlan(issueRef.repo, prd, cwd);
	if (plan.ordered.length === 0) {
		throw new Error(`No child slices labeled ready-for-agent for #${prd.number}.`);
	}
	return { repo: issueRef.repo, prd, plan };
}

export async function buildSlicePlan(repo: string, prd: Issue, cwd: string): Promise<SlicePlan> {
	const allReferenced = await ghJson<Issue[]>(cwd, [
		"issue",
		"list",
		"-R",
		repo,
		"--state",
		"all",
		"--limit",
		"200",
		"--search",
		`#${prd.number} in:body,comments`,
		"--json",
		"number,title,body,labels,state,comments,url",
	]);

	const children = allReferenced
		.filter((issue) => issue.number !== prd.number)
		.filter((issue) => isChildOfPrd(issue, prd.number));

	const ready: Issue[] = [];
	const skipped: SkippedSlice[] = [];
	for (const issue of children) {
		const labels = labelSet(issue);
		if (labels.has("ready-for-agent")) {
			ready.push(issue);
			continue;
		}
		skipped.push({
			issue,
			reason: labels.has("ready-for-human") ? "ready-for-human" : "missing ready-for-agent",
		});
	}

	const childrenByNumber = new Map(children.map((issue) => [issue.number, issue]));
	const readyByNumber = new Map(ready.map((issue) => [issue.number, issue]));
	const blockersBySlice = new Map<number, number[]>();

	for (const slice of ready) {
		const blockers = extractBlockers(issueBody(slice));
		blockersBySlice.set(slice.number, blockers);
		for (const blockerNumber of blockers) {
			if (blockerNumber === slice.number) throw new Error(`Slice #${slice.number} blocks itself.`);
			if (readyByNumber.has(blockerNumber)) continue;
			const blocker = childrenByNumber.get(blockerNumber) ?? (await fetchIssueOptional(repo, blockerNumber, cwd));
			if (!blocker) throw new Error(`Slice #${slice.number} lists missing blocker #${blockerNumber}.`);
			if (blocker.state !== "CLOSED") {
				throw new Error(`Slice #${slice.number} is blocked by open issue #${blockerNumber}, which is not included in this run.`);
			}
		}
	}

	return { ordered: topologicalOrder(ready, blockersBySlice), skipped, blockersBySlice };
}

export function topologicalOrder(issues: Issue[], blockersBySlice: Map<number, number[]>): Issue[] {
	const issueByNumber = new Map(issues.map((issue) => [issue.number, issue]));
	const indegree = new Map(issues.map((issue) => [issue.number, 0]));
	const dependents = new Map<number, number[]>();

	for (const issue of issues) {
		for (const blocker of blockersBySlice.get(issue.number) ?? []) {
			if (!issueByNumber.has(blocker)) continue;
			indegree.set(issue.number, (indegree.get(issue.number) ?? 0) + 1);
			dependents.set(blocker, [...(dependents.get(blocker) ?? []), issue.number]);
		}
	}

	const queue = issues.filter((issue) => indegree.get(issue.number) === 0).sort((a, b) => a.number - b.number);
	const ordered: Issue[] = [];
	while (queue.length > 0) {
		const issue = queue.shift();
		if (!issue) break;
		ordered.push(issue);
		for (const dependentNumber of dependents.get(issue.number) ?? []) {
			const nextDegree = (indegree.get(dependentNumber) ?? 0) - 1;
			indegree.set(dependentNumber, nextDegree);
			if (nextDegree === 0) {
				const dependent = issueByNumber.get(dependentNumber);
				if (dependent) {
					queue.push(dependent);
					queue.sort((a, b) => a.number - b.number);
				}
			}
		}
	}

	if (ordered.length !== issues.length) {
		const cycle = issues
			.filter((issue) => !ordered.some((done) => done.number === issue.number))
			.map((issue) => `#${issue.number}`)
			.join(", ");
		throw new Error(`Blocked-by cycle among ready slices: ${cycle}`);
	}
	return ordered;
}
