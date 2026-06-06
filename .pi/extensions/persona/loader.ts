import fs from "node:fs/promises";
import path from "node:path";

import { AGENTS_DIR } from "./constants.ts";
import type { Persona } from "./types.ts";

export function stripFrontmatter(content: string): string {
	return content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trim();
}

export function isValidPersonaName(name: string): boolean {
	return /^[a-zA-Z0-9_-]+$/.test(name);
}

export function personaPath(cwd: string, name: string): string {
	return path.join(cwd, ...AGENTS_DIR, `${name}.md`);
}

export async function loadPersona(cwd: string, name: string): Promise<Persona> {
	if (!isValidPersonaName(name)) {
		throw new Error("Persona names may contain only letters, numbers, underscores, and hyphens.");
	}

	const filePath = personaPath(cwd, name);
	const raw = await fs.readFile(filePath, "utf8");
	const body = stripFrontmatter(raw);
	if (!body) throw new Error(`Persona file is empty after frontmatter: ${filePath}`);
	return { name, filePath, body };
}
