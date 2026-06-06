import type { Persona } from "./types.ts";

// Appends the active persona to the chained system prompt for one turn.
export function buildPersonaPrompt(systemPrompt: string, persona: Persona): string {
	return `${systemPrompt}

# Active Persona: ${persona.name}

The following persona was loaded from ${persona.filePath}. Follow it for this turn while preserving Pi's tool and safety rules. If the persona references native subagents, interpret that as producing a precise handoff prompt instead of assuming built-in subagent support.

${persona.body}
`;
}
