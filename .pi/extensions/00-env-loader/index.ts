import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const ENV_FILE = path.join(".pi", ".env");
const extensionDir = path.dirname(fileURLToPath(import.meta.url));
const projectRootFromExtension = path.resolve(extensionDir, "..", "..", "..");

type EnvLoaderGlobal = typeof globalThis & { __piEnvLoaderLoadedKeys?: Set<string> };

function loadedKeys(): Set<string> {
	const store = globalThis as EnvLoaderGlobal;
	store.__piEnvLoaderLoadedKeys ??= new Set<string>();
	return store.__piEnvLoaderLoadedKeys;
}

function unquoteEnvValue(value: string): string {
	const trimmed = value.trim();
	if (trimmed.length < 2) return trimmed;

	const first = trimmed[0];
	const last = trimmed[trimmed.length - 1];
	if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
		return trimmed.slice(1, -1);
	}

	return trimmed;
}

async function readEnvFile(filePath: string): Promise<Record<string, string>> {
	let text: string;
	try {
		text = await readFile(filePath, "utf8");
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
		throw error;
	}

	const values: Record<string, string> = {};
	for (const rawLine of text.split(/\r?\n/)) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#")) continue;

		const withoutExport = line.startsWith("export ") ? line.slice("export ".length).trimStart() : line;
		const equalsIndex = withoutExport.indexOf("=");
		if (equalsIndex === -1) continue;

		const key = withoutExport.slice(0, equalsIndex).trim();
		if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;

		values[key] = unquoteEnvValue(withoutExport.slice(equalsIndex + 1));
	}

	return values;
}

async function loadEnvFromProjectRoot(projectRoot: string): Promise<number> {
	const values = await readEnvFile(path.join(projectRoot, ENV_FILE));
	const ownedKeys = loadedKeys();
	let applied = 0;

	for (const [key, value] of Object.entries(values)) {
		if (process.env[key] !== undefined && !ownedKeys.has(key)) continue;
		if (process.env[key] !== value) applied += 1;
		process.env[key] = value;
		ownedKeys.add(key);
	}

	return applied;
}

export default async function (pi: ExtensionAPI) {
	await loadEnvFromProjectRoot(projectRootFromExtension);

	pi.on("session_start", async (_event, ctx) => {
		await loadEnvFromProjectRoot(ctx.cwd);
	});
}
