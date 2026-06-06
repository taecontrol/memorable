---
name: frame-problem
description: Verify and correctly frame a problem before any solution is proposed. Runs an autonomous discipline — confirm every claim against ground truth, decompose bundled concerns, separate symptom from root cause, enumerate unverified assumptions — and holds back all fixes until released. Use when the user says "understand this before proposing a fix", "don't jump to solutions / no recommendations yet", "what's the real problem here", "is this the root cause or a symptom", or hands you a problem statement (ADR draft, ticket, doc) to investigate rather than solve. Not for reproducible bugs (use diagnose) or stress-testing your own plan interactively (use grill-me).
---

# Frame Problem

Understand a problem correctly **before** anyone solves it. The deliverable is a *verified problem statement*, not a fix. Many agents jump to solutions — the entire value of this skill is resisting that.

## Mode: defer solutioning (always on)

While in this skill you produce **no fixes, no design proposals, no "I'd recommend…"** — only verified findings, decompositions, and unknowns. The **one** thing you may recommend is *what kind of artifact should follow* (fix / research / ADR / issue), because that's a framing decision, not a solution.

The mode releases **only** when the problem statement is complete **and** the user explicitly says go. Never self-release: end by presenting the framing and asking permission to move to solutioning.

**Not this skill:** a reproducible bug / regression / something throwing → `diagnose`. Stress-testing *your own* proposed plan → `grill-me`. If P1 reveals a clean reproducible bug, say so and hand off to `diagnose` rather than grinding all five phases.

Treat any problem statement (ADR draft, ticket, bug report, doc) as a **claim to verify, not ground truth** — it may be stale.

## P1 — Verify

Locate current evidence for every load-bearing claim and confirm or correct it. Note drift explicitly (line refs and versions move).

Self-questions:
- Do the artifact's claims still hold against the *current* code?
- Where does this dependency / symbol *actually* resolve from?
- Is it committed or ignored? Declared vs. resolved — do they match?
- Does CI / the deploy path enforce what I think it enforces?

A claim about behavior isn't understood until you've checked **where the behavior is actually pinned** — not just the one source file. Sweep the usual hiding places: cited source lines, dependency resolution / lockfiles, config, CI/deploy path, persistence/migrations, git history. *(Project flavor: a string in `wrangler.jsonc` is lower-risk than one in a D1 column or KV key; check whether CI freezes the lockfile.)*

If the framing touches **domain nouns**, check them against `docs/ubiquitous-language.md` — a problem stated in drifted vocabulary is itself a finding.

## P2 — Decompose

Explain the problem in plain language. Split bundled concerns: a lumped problem usually hides several independent decisions, each with its own **risk and reversibility**. Name what's **already mitigated** so the residual problem is precise.

## P3 — Reframe (self-checkpoint: "is this the real problem or a symptom?")

Before accepting the stated problem as *the* problem, ask whether it's the cause or a symptom of something deeper. Then name the **obvious overcorrection** and why it's wrong — don't let the reframe trigger an over-engineered swing.

## P4 — Checkpoint: anti-bluff gate (self-checkpoint: "do I fully understand?")

Ask yourself, before declaring understanding: **what am I asserting that I haven't verified?** Enumerate residual unknowns. For each load-bearing-but-unverified claim, either close it (loop back to P1) or get the fact only the user holds — operational reality, intent, history, deploy discipline. Ask one question at a time, with a recommended answer.

Never bluff "yes, I understand." The unknowns list must be empty of *load-bearing* items before you declare the framing complete.

**Plain-language test (strong anti-bluff check):** before declaring understanding, write the problem out in plain, jargon-free language — the way you'd explain it to the non-expert who owns it. If you can't, you don't understand it yet — loop back to P1. This explanation is a required deliverable (see Output), and it lets the user confirm the framing is actually right.

## P5 — Scope (self-checkpoint: "fix, or does this deserve an ADR?")

Recommend **what kind of artifact** the problem deserves — and don't over-ceremony it:
- Design problem needing the idiomatic grain → `research` / `deep-research` (design it twice).
- A hard-to-reverse, surprising, real-tradeoff decision → the **architect** / ADR criteria.
- Plain fix → `implement-ticket` / `tdd`. Already-framed bug → `diagnose`.

## Output: the verified problem statement

Inline by default (offer to persist only when it'll outlive the session or is handing off). A light skeleton, not a rigid template:

0. **Plain-English explanation** — *lead with this.* A short, jargon-free account a non-expert owner can read and say "yes, that's the problem." Describe the problem only — never a fix. Cover, in plain words: what you can do today (the apparent feature); what actually happens (the gap); why it matters (concrete user impact); the deeper issue (symptom vs root cause); and what's tangled together vs. what to keep separate. This is a deliverable in its own right, not a substitute for the verified statement below.
1. **Claims checked** — each → confirmed / corrected, with evidence path (`file:line`, CI rule, git ref). Drift noted.
2. **The problem, decomposed** — independent parts, each with risk/reversibility; what's already mitigated.
3. **Symptom vs. root cause** — and the overcorrection to avoid.
4. **Residual unknowns** — load-bearing claims still unverified; empty before declaring understanding.
5. **Suggested next artifact** — fix / research / ADR / issue (one line).
