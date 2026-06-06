import type {
	AutocompleteItem,
	ExtensionAPI,
	ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";

import { buildPersonaPrompt } from "./prompt.ts";
import { PersonaStore } from "./store.ts";

// Builtin subcommands. This map is the single source of truth for both command
// routing and autocompletion; any argument not found here is a persona name.
function buildSubcommands(
	store: PersonaStore,
): Record<string, (ctx: ExtensionCommandContext) => Promise<void>> {
	return {
		async status(ctx) {
			const available = await store.refreshKnown(ctx.cwd);
			const active = store.getActive();
			const current = active ? `Active persona: ${active.name}` : "No active persona";
			const suffix = available.length
				? `\nAvailable: ${available.join(", ")}`
				: "\nNo .claude/agents/*.md personas found";
			ctx.ui.notify(current + suffix, "info");
			store.updateIndicator(ctx);
		},

		async list(ctx) {
			const available = await store.refreshKnown(ctx.cwd);
			ctx.ui.notify(
				available.length ? `Personas: ${available.join(", ")}` : "No .claude/agents/*.md personas found",
				"info",
			);
		},

		async off(ctx) {
			store.disable(ctx);
			ctx.ui.notify("Persona disabled", "info");
		},

		async reload(ctx) {
			try {
				const persona = await store.reload(ctx);
				ctx.ui.notify(`Persona reloaded: ${persona.name}`, "info");
			} catch (error) {
				ctx.ui.notify((error as Error).message, "warning");
			}
		},
	};
}

export default function personaExtension(pi: ExtensionAPI) {
	const store = new PersonaStore(pi);
	const subcommands = buildSubcommands(store);

	pi.on("session_start", async (_event, ctx) => {
		store.restore(ctx);
		await store.refreshKnown(ctx.cwd);
		store.updateIndicator(ctx);
	});

	pi.on("session_tree", async (_event, ctx) => {
		store.restore(ctx);
		store.updateIndicator(ctx);
	});

	pi.registerCommand("persona", {
		description: "Load/toggle a Claude agent persona from .claude/agents/<name>.md",
		getArgumentCompletions: (prefix: string): AutocompleteItem[] => {
			return [...store.getKnown(), ...Object.keys(subcommands)]
				.filter((item) => item.startsWith(prefix))
				.map((item) => ({ value: item, label: item }));
		},
		handler: async (args, ctx) => {
			const command = args.trim();

			// No argument defaults to status.
			if (!command) {
				await subcommands.status(ctx);
				return;
			}

			const [name, ...rest] = command.split(/\s+/);
			if (rest.length > 0) {
				ctx.ui.notify("Usage: /persona <name>|off|status|list|reload", "error");
				return;
			}

			const subcommand = subcommands[name];
			if (subcommand) {
				await subcommand(ctx);
				return;
			}

			try {
				const persona = await store.activate(ctx, name);
				ctx.ui.notify(`Persona loaded: ${persona.name}`, "info");
			} catch (error) {
				ctx.ui.notify(`Failed to load persona: ${(error as Error).message}`, "error");
			}
		},
	});

	pi.on("before_agent_start", async (event) => {
		const active = store.getActive();
		if (!active) return undefined;
		return { systemPrompt: buildPersonaPrompt(event.systemPrompt, active) };
	});
}
