import fs from "node:fs/promises";
import path from "node:path";

import { AGENTS_DIR } from "./constants.ts";

// Lists available persona names from .claude/agents/*.md, sorted. Returns an
// empty list when the directory does not exist.
export async function listPersonas(cwd: string): Promise<string[]> {
	try {
		const dir = path.join(cwd, ...AGENTS_DIR);
		const entries = await fs.readdir(dir, { withFileTypes: true });
		return entries
			.filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
			.map((entry) => path.basename(entry.name, ".md"))
			.sort((a, b) => a.localeCompare(b));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
		throw error;
	}
}
