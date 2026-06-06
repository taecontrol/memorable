import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import { STATE_TYPE, STATUS_KEY } from "./constants.ts";
import { listPersonas } from "./discovery.ts";
import { loadPersona } from "./loader.ts";
import type { Persona, PersonaStateEntry } from "./types.ts";

// Owns all mutable persona state for an extension instance: the active persona
// and the last-known set of persona names used for autocompletion. Persists
// activation changes to the session and keeps the footer indicator in sync.
export class PersonaStore {
	private active: Persona | undefined;
	private known: string[] = [];

	constructor(private readonly pi: ExtensionAPI) {}

	getActive(): Persona | undefined {
		return this.active;
	}

	getKnown(): readonly string[] {
		return this.known;
	}

	// Reconstructs the active persona from the session branch (last write wins).
	restore(ctx: ExtensionContext): void {
		this.active = undefined;
		for (const entry of ctx.sessionManager.getBranch() as PersonaStateEntry[]) {
			if (entry.type !== "custom" || entry.customType !== STATE_TYPE) continue;
			this.active = entry.data?.active ? entry.data.persona : undefined;
		}
	}

	async refreshKnown(cwd: string): Promise<readonly string[]> {
		this.known = await listPersonas(cwd);
		return this.known;
	}

	// Loads and activates a persona by name. Throws on invalid name or read
	// failure; callers own user-facing error reporting.
	async activate(ctx: ExtensionContext, name: string): Promise<Persona> {
		this.active = await loadPersona(ctx.cwd, name);
		this.persist();
		this.updateIndicator(ctx);
		return this.active;
	}

	disable(ctx: ExtensionContext): void {
		this.active = undefined;
		this.persist();
		this.updateIndicator(ctx);
	}

	// Reloads the active persona from disk. Throws if none is active.
	async reload(ctx: ExtensionContext): Promise<Persona> {
		if (!this.active) throw new Error("No active persona to reload");
		return this.activate(ctx, this.active.name);
	}

	updateIndicator(ctx: ExtensionContext): void {
		if (!ctx.hasUI) return;

		if (!this.active) {
			ctx.ui.setStatus(STATUS_KEY, undefined);
			return;
		}

		const text = `persona: ${this.active.name}`;
		const styled = ctx.ui.theme?.fg ? ctx.ui.theme.fg("accent", text) : text;
		ctx.ui.setStatus(STATUS_KEY, styled);
	}

	private persist(): void {
		this.pi.appendEntry(STATE_TYPE, this.active ? { active: true, persona: this.active } : { active: false });
	}
}
