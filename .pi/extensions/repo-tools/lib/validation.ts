import path from "node:path";

const REPO_PATH_PATTERN = /^[A-Za-z0-9_./@+=,\-]+$/;
const GITHUB_REPO_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const REF_FORBIDDEN_PATTERN = /[\s~^:?*\[\\]/;
const CLAUDE_COAUTHOR_PATTERN = /^Co-authored-by:\s*Claude\b/im;

export function normalizePathArgument(value: string): string {
	return value.startsWith("@") ? value.slice(1) : value;
}

export function validateTimeoutSeconds(value: number | undefined, defaultSeconds: number): number {
	if (value === undefined) return defaultSeconds;
	if (!Number.isInteger(value)) throw new Error("timeout_seconds must be an integer.");
	if (value < 5 || value > 600) throw new Error("timeout_seconds must be between 5 and 600.");
	return value;
}

export function validateLineOffset(value: number | undefined): number | undefined {
	if (value === undefined) return undefined;
	if (!Number.isInteger(value)) throw new Error("offset must be an integer.");
	if (value < 1 || value > 1_000_000) throw new Error("offset must be between 1 and 1,000,000.");
	return value;
}

export function validateLineLimit(value: number | undefined): number | undefined {
	if (value === undefined) return undefined;
	if (!Number.isInteger(value)) throw new Error("limit must be an integer.");
	if (value < 1 || value > 2_000) throw new Error("limit must be between 1 and 2,000.");
	return value;
}

export function validateCount(value: number | undefined, defaultValue: number, maxValue: number, label: string): number {
	if (value === undefined) return defaultValue;
	if (!Number.isInteger(value)) throw new Error(`${label} must be an integer.`);
	if (value < 1 || value > maxValue) throw new Error(`${label} must be between 1 and ${maxValue}.`);
	return value;
}

export function validatePositiveSafeInteger(value: number | undefined, label: string): number | undefined {
	if (value === undefined) return undefined;
	if (!Number.isSafeInteger(value)) throw new Error(`${label} must be a safe integer.`);
	if (value < 1) throw new Error(`${label} must be positive.`);
	return value;
}

export function requirePositiveSafeInteger(value: number | undefined, label: string): number {
	const validated = validatePositiveSafeInteger(value, label);
	if (validated === undefined) throw new Error(`${label} is required.`);
	return validated;
}

export function validateRepoPaths(cwd: string, paths: string[] | undefined, label = "paths"): string[] {
	if (!paths) return [];
	if (paths.length > 50) throw new Error(`${label} accepts at most 50 entries.`);

	return paths.map((rawPath) => validateRepoPath(cwd, rawPath, label));
}

export function validateRequiredRepoPaths(cwd: string, paths: string[] | undefined, label = "paths"): string[] {
	const validated = validateRepoPaths(cwd, paths, label);
	if (validated.length === 0) throw new Error(`${label} requires at least one path.`);
	return validated;
}

export function validateRepoPath(cwd: string, rawPath: string, label = "path"): string {
	const value = normalizePathArgument(rawPath.trim()).replace(/\/$/, "");
	if (!value) throw new Error(`${label} cannot contain empty entries.`);
	if (value.startsWith("-")) throw new Error(`${label} cannot start with '-': ${rawPath}`);
	if (path.isAbsolute(value)) throw new Error(`${label} must be relative: ${rawPath}`);
	if (value.includes("..")) throw new Error(`${label} cannot contain '..': ${rawPath}`);
	if (value.includes(":")) throw new Error(`${label} cannot contain ':': ${rawPath}`);
	if (!REPO_PATH_PATTERN.test(value)) throw new Error(`${label} has unsupported characters: ${rawPath}`);

	const resolved = path.resolve(cwd, value);
	const root = path.resolve(cwd);
	if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
		throw new Error(`${label} escapes project root: ${rawPath}`);
	}

	return value;
}

export function validateBranchName(value: string, label = "branch"): string {
	const branch = value.trim();
	validateRefLike(branch, label);
	if (branch.includes("@")) throw new Error(`${label} cannot contain '@'.`);
	return branch;
}

export function validateOptionalRef(value: string | undefined, label = "ref"): string | undefined {
	if (value === undefined) return undefined;
	const ref = value.trim();
	validateRefLike(ref, label);
	return ref;
}

export function validateGithubRepo(value: string | undefined): string | undefined {
	if (value === undefined) return undefined;
	const repo = value.trim();
	if (!repo) throw new Error("repo cannot be empty.");
	if (repo.length > 120) throw new Error("repo is too long; max 120 characters.");
	if (!GITHUB_REPO_PATTERN.test(repo)) throw new Error("repo must look like owner/name.");
	if (repo.split("/").some((part) => part.startsWith("-") || part.endsWith("-"))) {
		throw new Error("repo owner/name parts cannot start or end with '-'.");
	}
	return repo;
}

export function validateIssueRef(value: string | undefined): string | undefined {
	if (value === undefined) return undefined;
	const issue = value.trim();
	if (!issue) throw new Error("issue cannot be empty.");
	if (issue.length > 240) throw new Error("issue is too long; max 240 characters.");
	return issue;
}

export function validateCommitMessage(value: string): string {
	const message = value.trim();
	if (!message) throw new Error("message cannot be empty.");
	if (message.length > 4_000) throw new Error("message is too long; max 4,000 characters.");
	if (CLAUDE_COAUTHOR_PATTERN.test(message)) {
		throw new Error("message cannot include a Co-authored-by: Claude trailer.");
	}
	return message;
}

export function validateTitle(value: string, label = "title"): string {
	const title = value.trim();
	if (!title) throw new Error(`${label} cannot be empty.`);
	if (title.length > 300) throw new Error(`${label} is too long; max 300 characters.`);
	return title;
}

export function validateBody(value: string | undefined, label = "body"): string | undefined {
	if (value === undefined) return undefined;
	const body = value.trim();
	if (body.length > 20_000) throw new Error(`${label} is too long; max 20,000 characters.`);
	return body;
}

function validateRefLike(value: string, label: string): void {
	if (!value) throw new Error(`${label} cannot be empty.`);
	if (value.length > 120) throw new Error(`${label} is too long; max 120 characters.`);
	if (value.startsWith("-")) throw new Error(`${label} cannot start with '-'.`);
	if (value.startsWith("/") || value.endsWith("/")) throw new Error(`${label} cannot start or end with '/'.`);
	if (value.endsWith(".")) throw new Error(`${label} cannot end with '.'.`);
	if (value === "@") throw new Error(`${label} cannot be '@'.`);
	if (value.includes("..")) throw new Error(`${label} cannot contain '..'.`);
	if (value.includes("//")) throw new Error(`${label} cannot contain '//'.`);
	if (value.includes("@{")) throw new Error(`${label} cannot contain '@{'.`);
	if (REF_FORBIDDEN_PATTERN.test(value)) throw new Error(`${label} contains unsupported git ref characters.`);
	for (const component of value.split("/")) {
		if (!component) throw new Error(`${label} contains an empty path component.`);
		if (component.startsWith(".")) throw new Error(`${label} components cannot start with '.'.`);
		if (component.endsWith(".lock")) throw new Error(`${label} components cannot end with '.lock'.`);
	}
}
