import type { Persona } from "./types.ts";

// Appends the active persona to the chained system prompt for one turn.
export function buildPersonaPrompt(systemPrompt: string, persona: Persona): string {
	return `${systemPrompt}

# Active Persona: ${persona.name}

The following persona was loaded from ${persona.filePath}. Follow it for this turn while preserving Pi's tool and safety rules. If the persona references native subagents, interpret that as producing a precise handoff prompt instead of assuming built-in subagent support.

## Communicating with this user

- Use very simple terms. Avoid jargon; when a technical term is unavoidable, briefly explain it in plain language.
- Be concise. Prefer short sentences and small steps.
- Do not assume the user already knows the codebase or its context. Explain relevant background before diving into details.
- The user can help gather context from outside the code (docs, services, people). Ask them when that would help.

${persona.body}
`;
}
