import fs from "node:fs/promises";
import path from "node:path";

type Persona = {
	name: string;
	filePath: string;
	body: string;
};

type PersonaStateEntry = {
	type: string;
	customType?: string;
	data?: {
		active?: boolean;
		persona?: Persona;
	};
};

const STATE_TYPE = "persona-state";
const STATUS_KEY = "persona";
const AGENTS_DIR = [".claude", "agents"];

let active: Persona | undefined;
let knownPersonas: string[] = [];

function stripFrontmatter(content: string): string {
	return content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trim();
}

function isValidPersonaName(name: string): boolean {
	return /^[a-zA-Z0-9_-]+$/.test(name);
}

function personaPath(cwd: string, name: string): string {
	return path.join(cwd, ...AGENTS_DIR, `${name}.md`);
}

async function listPersonas(cwd: string): Promise<string[]> {
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

async function refreshKnownPersonas(cwd: string): Promise<string[]> {
	knownPersonas = await listPersonas(cwd);
	return knownPersonas;
}

function restore(ctx: any): void {
	active = undefined;
	for (const entry of ctx.sessionManager.getBranch() as PersonaStateEntry[]) {
		if (entry.type !== "custom" || entry.customType !== STATE_TYPE) continue;
		active = entry.data?.active ? entry.data.persona : undefined;
	}
}

function updateIndicator(ctx: any): void {
	if (!ctx.hasUI) return;

	if (!active) {
		ctx.ui.setStatus(STATUS_KEY, undefined);
		return;
	}

	const text = `persona: ${active.name}`;
	const styled = ctx.ui.theme?.fg ? ctx.ui.theme.fg("accent", text) : text;
	ctx.ui.setStatus(STATUS_KEY, styled);
}

function persist(pi: any, persona: Persona | undefined): void {
	pi.appendEntry(STATE_TYPE, persona ? { active: true, persona } : { active: false });
}

async function loadPersona(cwd: string, name: string): Promise<Persona> {
	if (!isValidPersonaName(name)) {
		throw new Error("Persona names may contain only letters, numbers, underscores, and hyphens.");
	}

	const filePath = personaPath(cwd, name);
	const raw = await fs.readFile(filePath, "utf8");
	const body = stripFrontmatter(raw);
	if (!body) throw new Error(`Persona file is empty after frontmatter: ${filePath}`);
	return { name, filePath, body };
}

export default function personaExtension(pi: any) {
	pi.on("session_start", async (_event: unknown, ctx: any) => {
		restore(ctx);
		await refreshKnownPersonas(ctx.cwd);
		updateIndicator(ctx);
	});

	pi.on("session_tree", async (_event: unknown, ctx: any) => {
		restore(ctx);
		updateIndicator(ctx);
	});

	pi.registerCommand("persona", {
		description: "Load/toggle a Claude agent persona from .claude/agents/<name>.md",
		getArgumentCompletions: (prefix: string) => {
			const builtins = ["status", "list", "off", "reload"];
			return [...knownPersonas, ...builtins]
				.filter((item) => item.startsWith(prefix))
				.map((item) => ({ value: item, label: item }));
		},
		handler: async (args: string, ctx: any) => {
			const command = args.trim();

			if (!command || command === "status") {
				const available = await refreshKnownPersonas(ctx.cwd);
				const current = active ? `Active persona: ${active.name}` : "No active persona";
				const suffix = available.length ? `\nAvailable: ${available.join(", ")}` : "\nNo .claude/agents/*.md personas found";
				ctx.ui.notify(current + suffix, "info");
				updateIndicator(ctx);
				return;
			}

			if (command === "list") {
				const available = await refreshKnownPersonas(ctx.cwd);
				ctx.ui.notify(available.length ? `Personas: ${available.join(", ")}` : "No .claude/agents/*.md personas found", "info");
				return;
			}

			if (command === "off") {
				active = undefined;
				persist(pi, active);
				updateIndicator(ctx);
				ctx.ui.notify("Persona disabled", "info");
				return;
			}

			if (command === "reload") {
				if (!active) {
					ctx.ui.notify("No active persona to reload", "warning");
					return;
				}
				active = await loadPersona(ctx.cwd, active.name);
				persist(pi, active);
				updateIndicator(ctx);
				ctx.ui.notify(`Persona reloaded: ${active.name}`, "info");
				return;
			}

			const [name, ...rest] = command.split(/\s+/);
			if (!name || rest.length > 0) {
				ctx.ui.notify("Usage: /persona <name>|off|status|list|reload", "error");
				return;
			}

			try {
				active = await loadPersona(ctx.cwd, name);
				persist(pi, active);
				updateIndicator(ctx);
				ctx.ui.notify(`Persona loaded: ${active.name}`, "info");
			} catch (error) {
				ctx.ui.notify(`Failed to load persona: ${(error as Error).message}`, "error");
			}
		},
	});

	pi.on("before_agent_start", async (event: { systemPrompt: string }) => {
		if (!active) return undefined;

		return {
			systemPrompt: `${event.systemPrompt}

# Active Persona: ${active.name}

The following persona was loaded from ${active.filePath}. Follow it for this turn while preserving Pi's tool and safety rules. If the persona references native subagents, interpret that as producing a precise handoff prompt instead of assuming built-in subagent support.

${active.body}
`,
		};
	});
}
