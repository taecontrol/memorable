import type { Issue } from "./types.ts";

export function issueText(issue: Issue): string {
	return `${issueBody(issue)}\n${formatComments(issue)}`;
}

export function issueBody(issue: Issue): string {
	return issue.body ?? "";
}

export function formatComments(issue: Issue): string {
	const comments = issue.comments ?? [];
	if (comments.length === 0) return "No comments.";
	return comments
		.map((comment, index) => {
			const author = comment.author?.login ? ` by ${comment.author.login}` : "";
			const createdAt = comment.createdAt ? ` at ${comment.createdAt}` : "";
			return `Comment ${index + 1}${author}${createdAt}:\n${comment.body ?? ""}`;
		})
		.join("\n\n");
}

export function labelSet(issue: Issue): Set<string> {
	return new Set((issue.labels ?? []).map((label) => label.name));
}

export function extractBlockers(body: string): number[] {
	const section = extractMarkdownSection(body, "Blocked by");
	if (section) return issueRefs(section);
	const lineMatch = /^Blocked by:\s*(.+)$/im.exec(body);
	return lineMatch ? issueRefs(lineMatch[1]) : [];
}

export function extractMarkdownSection(markdown: string, heading: string): string | undefined {
	const lines = markdown.split(/\r?\n/);
	const wanted = heading.toLowerCase();
	const collected: string[] = [];
	let inSection = false;

	for (const line of lines) {
		const headingMatch = /^(#{2,6})\s+(.+?)\s*$/.exec(line);
		if (headingMatch) {
			if (inSection) break;
			inSection = headingMatch[2].trim().toLowerCase() === wanted;
			continue;
		}
		if (inSection) collected.push(line);
	}

	return inSection || collected.length > 0 ? collected.join("\n") : undefined;
}

export function issueRefs(text: string): number[] {
	const refs = new Set<number>();
	for (const match of text.matchAll(/#(\d+)\b/g)) refs.add(Number(match[1]));
	return [...refs];
}

export function isChildOfPrd(issue: Issue, prdNumber: number): boolean {
	const text = issueText(issue);
	if (new RegExp(`\\bParent:\\s*#${prdNumber}\\b`, "i").test(text)) return true;

	const parentSection = extractMarkdownSection(text, "Parent");
	if (parentSection && issueRefs(parentSection).includes(prdNumber)) return true;

	return issueRefs(text).includes(prdNumber);
}
