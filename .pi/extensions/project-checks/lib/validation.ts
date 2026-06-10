import path from "node:path";

const TEST_TARGET_PATTERN = /^[A-Za-z0-9_./:\-\[\]]+$/;
const PROJECT_PATH_PATTERN = /^[A-Za-z0-9_./:\-]+$/;
const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const KEYWORD_TOKEN_PATTERN = /^[A-Za-z0-9_()\s]+$/;

const MARKER_IDENTIFIERS = new Set(["integration"]);
const BOOLEAN_OPERATORS = new Set(["and", "or", "not"]);

export function normalizePathArgument(value: string): string {
	return value.startsWith("@") ? value.slice(1) : value;
}

export function validateTimeoutSeconds(value: number | undefined, defaultSeconds: number): number {
	if (value === undefined) return defaultSeconds;
	if (!Number.isInteger(value)) throw new Error("timeout_seconds must be an integer.");
	if (value < 5 || value > 600) throw new Error("timeout_seconds must be between 5 and 600.");
	return value;
}

export function validateMaxfail(value: number | undefined): number | undefined {
	if (value === undefined) return undefined;
	if (!Number.isInteger(value)) throw new Error("maxfail must be an integer.");
	if (value < 1 || value > 50) throw new Error("maxfail must be between 1 and 50.");
	return value;
}

export function validateTestTargets(cwd: string, targets: string[] | undefined): string[] {
	if (!targets) return [];
	if (targets.length > 20) throw new Error("targets accepts at most 20 entries.");

	return targets.map((rawTarget) => {
		const target = normalizePathArgument(rawTarget.trim());
		if (!target) throw new Error("targets cannot contain empty entries.");
		if (target.startsWith("-")) throw new Error(`Test target cannot start with '-': ${rawTarget}`);
		if (path.isAbsolute(target)) throw new Error(`Test target must be relative: ${rawTarget}`);
		if (target.includes("..")) throw new Error(`Test target cannot contain '..': ${rawTarget}`);
		if (!target.startsWith("tests/")) throw new Error(`Test target must be under tests/: ${rawTarget}`);
		if (!TEST_TARGET_PATTERN.test(target)) {
			throw new Error(`Test target has unsupported characters: ${rawTarget}`);
		}

		const filePart = target.split("::", 1)[0] ?? target;
		const resolved = path.resolve(cwd, filePart);
		const testsRoot = path.resolve(cwd, "tests");
		if (resolved !== testsRoot && !resolved.startsWith(`${testsRoot}${path.sep}`)) {
			throw new Error(`Test target escapes tests/: ${rawTarget}`);
		}

		return target;
	});
}

export function validateKeywordExpression(value: string | undefined): string | undefined {
	if (value === undefined) return undefined;
	const expression = value.trim();
	if (!expression) throw new Error("keyword cannot be empty.");
	if (expression.length > 120) throw new Error("keyword is too long; max 120 characters.");
	if (!KEYWORD_TOKEN_PATTERN.test(expression)) {
		throw new Error("keyword may only contain identifiers, spaces, and parentheses.");
	}
	validateBooleanExpressionTokens(expression, "keyword");
	return expression;
}

export function validateMarkerExpression(value: string | undefined): string | undefined {
	if (value === undefined) return undefined;
	const expression = value.trim();
	if (!expression) throw new Error("marker cannot be empty.");
	if (expression.length > 120) throw new Error("marker is too long; max 120 characters.");
	if (!KEYWORD_TOKEN_PATTERN.test(expression)) {
		throw new Error("marker may only contain identifiers, spaces, and parentheses.");
	}
	validateBooleanExpressionTokens(expression, "marker", MARKER_IDENTIFIERS);
	return expression;
}

export function validateLintPaths(cwd: string, paths: string[] | undefined): string[] {
	if (!paths || paths.length === 0) return ["."];
	if (paths.length > 50) throw new Error("paths accepts at most 50 entries.");

	return paths.map((rawPath) => {
		const value = normalizePathArgument(rawPath.trim()).replace(/\/$/, "");
		if (!value) throw new Error("paths cannot contain empty entries.");
		if (value.startsWith("-")) throw new Error(`Lint path cannot start with '-': ${rawPath}`);
		if (path.isAbsolute(value)) throw new Error(`Lint path must be relative: ${rawPath}`);
		if (value.includes("..")) throw new Error(`Lint path cannot contain '..': ${rawPath}`);
		if (!PROJECT_PATH_PATTERN.test(value)) throw new Error(`Lint path has unsupported characters: ${rawPath}`);
		if (!isAllowedLintPath(value)) {
			throw new Error(`Lint path must be '.', src/, tests/, scripts/, or pyproject.toml: ${rawPath}`);
		}

		const resolved = path.resolve(cwd, value);
		const root = path.resolve(cwd);
		if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
			throw new Error(`Lint path escapes project root: ${rawPath}`);
		}

		return value;
	});
}

function validateBooleanExpressionTokens(value: string, label: string, allowedIdentifiers?: Set<string>): void {
	const tokens = value.match(/[()]|[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
	const compact = tokens.join("");
	const compactInput = value.replace(/\s+/g, "");
	if (compact !== compactInput) throw new Error(`${label} contains invalid syntax.`);

	let depth = 0;
	for (const token of tokens) {
		if (token === "(") {
			depth += 1;
			continue;
		}
		if (token === ")") {
			depth -= 1;
			if (depth < 0) throw new Error(`${label} has unbalanced parentheses.`);
			continue;
		}
		if (BOOLEAN_OPERATORS.has(token)) continue;
		if (!IDENTIFIER_PATTERN.test(token)) throw new Error(`${label} contains an invalid identifier: ${token}`);
		if (allowedIdentifiers && !allowedIdentifiers.has(token)) {
			throw new Error(`${label} identifier is not allowed: ${token}`);
		}
	}
	if (depth !== 0) throw new Error(`${label} has unbalanced parentheses.`);
}

function isAllowedLintPath(value: string): boolean {
	return (
		value === "." ||
		value === "src" ||
		value.startsWith("src/") ||
		value === "tests" ||
		value.startsWith("tests/") ||
		value === "scripts" ||
		value.startsWith("scripts/") ||
		value === "pyproject.toml"
	);
}
