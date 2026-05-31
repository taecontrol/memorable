# ADR 0014: Write Policy Removed From V1

Date: 2026-05-30
Status: Accepted

## Context

The product charter references a write policy in its Agent Experience section: agents may write memory automatically "subject to the project's write policy," and "sensitive categories can require suggestion or confirmation." `Write Policy` and `Sensitive Category` are both Accepted Language in `docs/ubiquitous-language.md`.

The current implementation reflects none of that intent. `MemoryProfile` carries a `WritePolicy` dataclass with two string fields (`default`, `sensitive`), parsed from the profile YAML in `load_profile_from_yaml`. The values are:

- not validated (any string is accepted — there is no allowed vocabulary);
- not enforced at write time (no Sensitive Category detection, no write interception — no application service reads the policy);
- surfaced in the profile-inspect CLI output and in the MCP profile output.

The V1 `init` scaffold (ADR-adjacent decision in the V1 release plan) wrote a `write_policy:` block into every new profile. The combined effect: a Human Owner who reads `sensitive: suggest` — in the scaffold, in inspect output, or in the MCP profile — would reasonably assume the value protects them. It does nothing. The field is a silent guarantee that the system never honors.

V1 does not include write-time enforcement, Sensitive Category detection, or any agent contract that the policy is honored. Building those is out of scope for the tracer-bullet release.

## Decision

Remove `write_policy` entirely from V1 rather than ship it inert.

Specifically:

1. Remove the `write_policy:` block from the `init` scaffold (amends the V1 scaffold decision).
2. Remove the `WritePolicy` dataclass and the `write_policy` field from `MemoryProfile`.
3. Remove its parsing from `load_profile_from_yaml`.
4. Remove `write_policy_default` / `write_policy_sensitive` from the profile-inspect CLI output and the MCP profile output.

A `write_policy:` key in a hand-written profile becomes an unrecognized key: tolerated and silently ignored on load (no parse failure), and shown nowhere. **(Amended — see below.)**

Write policy returns only as a real feature — with a defined vocabulary, write-time enforcement, and Sensitive Category detection — designed in a future ADR. It will not return as a config-only knob.

## Consequences

Positive:

- No misleading surface. Nothing displays a policy value that nothing honors.
- No dead code. No parsing or dataclass for a field no service reads.
- Safe at 0.0.1: an output-shape break is expected at patch level on the version ladder, and an unknown YAML key loads without error.
- The concept survives where it belongs. `Write Policy` and `Sensitive Category` remain Accepted Language; a glossary holds domain concepts regardless of build status, so no language change is required.

Negative:

- Charter intent ("subject to the project's write policy") has no V1 realization. A reader of the charter will find no corresponding code — this ADR is the pointer that explains why.
- Re-introduction must rebuild the profile field, parsing, and surfacing that this ADR removes. That cost is accepted in exchange for not shipping a silent guarantee.

## Alternatives Considered

**Ship as dead config**: keep parsing and surfacing as human-readable intent, document that nothing honors it. Rejected: the inspect and MCP output still read as a guarantee. The honesty problem is the surface, not just the scaffold; keeping the surface keeps the lie.

**Advisory contract the Agent honors**: surface the policy to the Agent via MCP and document that the Agent is expected to honor it, with the kernel not enforcing and compliance unverified. Rejected for V1: an unverified "contract" that nothing checks is the same false guarantee in a different costume. A genuine agent contract needs at least a way to observe compliance, which V1 does not have.

**Scaffold-only removal**: strip the block from the scaffold but keep the dataclass, parsing, and surfacing. Rejected: half-delivers the honesty goal — the misleading value simply moves from the scaffold to inspect/MCP output, and leaves dead parsing code a future contributor must puzzle over.

## Amendment (2026-05-30): write_policy is rejected, not silently tolerated

ADR-0017 (fail-loud profile validation) reverses the "tolerated and silently ignored on load" clause of this ADR. Under ADR-0017 the profile parser rejects unknown keys, so a `write_policy:` block now fails validation with an actionable message ("removed in v1 (ADR-0014); remove this block") instead of loading silently. The removal of the dataclass, parsing, and inspect/MCP surfaces decided here is unchanged; only the disposition of a stray key changes — from silent drop to loud rejection. Rationale: a silent no-op gives an agent no signal to self-correct, which is the precise footgun fail-loud exists to remove.
