# ADR 0002: Use Project Memory Profiles To Specialize The Universal Kernel

Date: 2026-05-23
Status: Accepted

## Context

Memorable is project-scoped by default. Different workspaces have different memory shapes.

A software project may need components, APIs, architecture decisions, bugs, benchmarks, dependencies, and implementation notes.

A work folder may need meetings, commitments, stakeholders, documents, status updates, risks, and follow-ups.

A training project may need athlete profile, races, season plans, training phases, workout plans, workout events, measurements, rules, risk signals, weekly reviews, and action items.

A single universal schema centered only on tasks, decisions, observations, and relations would flatten too much. At the same time, every project cannot be allowed to invent an incompatible memory universe with no shared semantics.

## Decision

Use a small universal memory kernel plus project memory profiles.

The universal kernel contains concepts Memorable always understands:

- `MemorySpace`
- `MemoryProfile`
- `Source` or `Episode`
- `Entity`
- `MemoryRecord`
- `Evidence`
- `Observation`
- `Measurement`
- `Event`
- `Relation`
- `Decision`
- `Task`
- `DerivedMemory`

Each workspace may define a project memory profile that specializes the kernel with domain-specific structure:

- entity types;
- record types;
- relation types;
- metric keys, units, and scales;
- workflows that produce memory;
- write policies;
- sensitive categories;
- lifecycle rules;
- common current-state and point-in-time queries.

The first representation should be a versioned project file at `.memorable/memory.yaml`.

The durable decision is the existence of a project memory profile. The exact YAML schema can evolve through later specs and ADRs.

## Initial Profile Shape

This is a provisional sketch, not a final schema:

```yaml
version: 1

space:
  name: memorable
  description: Agent memory system design

write_policy:
  default: auto
  sensitive: suggest

entities:
  - name: Project
  - name: Component
  - name: StorageAdapter

records:
  - name: ArchitectureDecision
    extends: Decision
  - name: OpenQuestion
    extends: MemoryRecord
  - name: ResearchFinding
    extends: Evidence

metrics: []

workflows:
  - name: design_session
    produces:
      - ArchitectureDecision
      - OpenQuestion
      - ResearchFinding

common_queries:
  - name: current_decisions
  - name: open_questions
  - name: recent_changes
```

For a training workspace, the same shape might define metrics and records like:

```yaml
version: 1

space:
  name: triathlons

entities:
  - name: Race
  - name: TrainingPhase
  - name: Workout
  - name: Gear

records:
  - name: WeekPlan
    extends: MemoryRecord
  - name: WorkoutEvent
    extends: Event
  - name: WeeklyReview
    extends: DerivedMemory
  - name: RiskSignal
    extends: Evidence

metrics:
  - key: sleep_hours
    unit: hours
  - key: fatigue
    unit: rpe
    scale: 1-10

workflows:
  - name: weekly_review
    produces:
      - WeeklyReview
      - ActionItem
      - Measurement
      - RiskSignal
```

## Schema Evolution

Agents may propose profile changes when they detect repeated patterns.

Examples:

- "This project repeatedly records workout plans and workout events. Add `WorkoutPlan` and `WorkoutEvent`?"
- "This codebase stores many benchmark results. Add `BenchmarkMeasurement`?"
- "Meeting follow-ups keep appearing. Add `Commitment` as a project record type?"

Profile changes require human approval. Agents can suggest, explain, and draft changes, but should not silently mutate the project memory schema.

## Consequences

Positive:

- Each project can have a memory shape that fits its domain.
- The universal kernel preserves cross-project semantics for time, provenance, evidence, tasks, decisions, relations, and measurements.
- Agents can validate writes instead of spraying arbitrary labels and properties into the graph.
- Project memory can start imperfectly and improve over time.

Negative:

- Memorable needs profile parsing, validation, migration, and review workflows.
- Agents need guidance for proposing good schema changes.
- Too much profile complexity could make memory feel heavy, so `Observation` and `Evidence` remain important escape hatches.

## Guardrails

- A profile specializes the universal kernel; it does not replace it.
- A missing type should not block useful memory. Use `Observation` or `Evidence` as a fallback.
- A profile should define only useful structure, not an ontology for its own sake.
- Profile changes must be reviewable.
- Sensitive domains can use stricter write policies.

