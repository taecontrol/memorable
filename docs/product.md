# Memorable Product Charter

Date: 2026-05-23

## Core Promise

Memorable is a project-scoped GraphRAG memory system for agents.

Its purpose is to let agents remember and reliably retrieve decisions, facts, tasks, evidence, events, and context so humans do not have to repeat themselves or maintain Markdown files as the source of truth.

Markdown, chat summaries, plans, reports, reviews, and documents are outputs or views of memory. They are not the canonical memory store.

## Audience

This document is the product compass for future agents, contributors, and humans shaping Memorable. A fresh agent should be able to read it and make product decisions that still feel like Memorable.

Memorable's primary users are agents. Humans are the owners, reviewers, and beneficiaries of the memory.

## Product Identity

Memorable is:

- a structured, queryable, temporal memory layer for agents;
- a GraphRAG retrieval system that combines semantic search, graph context, temporal filtering, and provenance;
- scoped by workspace or project by default;
- local-first by default, with cloud storage as an explicit choice;
- built around agent-owned writes and human inspectability;
- designed to replace ad hoc Markdown tracking for decisions, facts, tasks, and durable context.

Memorable is not:

- a note-taking app;
- a passive file indexer;
- one global undifferentiated memory;
- a hidden LLM extraction pipeline;
- a Markdown folder with search;
- a wrapper around a specific storage library.

## Product Principles

1. Agents remember so humans do not repeat themselves.

Agents should be able to carry project context across sessions without humans restating decisions, preferences, constraints, commitments, or project history.

2. Memory is project-scoped by default.

Each workspace or folder should have its own memory space. A work notebook, a software project, and a training project can have different memory structures. Shared or global memory may exist later, but it is not the default.

3. Agents own memory writes.

Agents decide what is worth remembering and call Memorable tools intentionally. If a user wants files, meetings, or documents ingested, they ask an agent to do that work. Memorable should not passively ingest a workspace by default.

4. Humans own the memory.

Automatic agent writes are allowed, but memory must be inspectable and correctable. Humans need simple workflows to ask what was remembered, why it was remembered, what is current, what is stale, and how to correct it.

5. Markdown is a view, not storage.

Agents can generate Markdown summaries, weekly reviews, project briefs, architecture logs, or meeting recaps from memory. If a human edits those outputs, an agent may intentionally ingest the edits back into memory, but the document itself is not canonical unless its contents are written as structured memory.

6. Temporal semantics are core.

The product must represent what was true then, what is true now, what was superseded, what was completed, what was contradicted, and why. Time is not metadata sprinkled on top of notes. It is part of the model.

7. Provenance is required, boilerplate is not.

Every memory write should record where it came from and why it is believed: conversation, file, meeting, tool result, user instruction, generated analysis, or other source. This provenance belongs in the stored record and should not create repetitive chat output.

8. Uncertainty should be recorded only when it matters.

Memorable should preserve uncertainty when it affects how a memory should be used, but it should not force fake precision or repetitive user-facing boilerplate. The exact certainty vocabulary belongs in the schema and tool contracts, not in this charter.

9. Project schemas specialize a universal kernel.

Memorable should have a small universal memory kernel, then let each workspace define a memory profile for domain-specific entities, records, metrics, workflows, policies, and common queries.

10. Schema evolution is proposed by agents and approved by humans.

Agents may notice repeated patterns and propose updates to a project memory profile. They should not silently mutate the memory structure into chaos.

## Core Product Concepts

Memorable should have a small universal memory kernel that works across projects. The kernel gives agents shared language for memory spaces, sources, entities, evidence, events, relations, decisions, tasks, measurements, and derived summaries.

Project memory profiles specialize that kernel for a specific workspace. They should let a software project, work folder, or training notebook define the memory shape that fits its domain without losing shared temporal and provenance semantics.

Retrieval is part of the product model, not a later convenience layer. Memorable should use GraphRAG retrieval: embeddings over derived indexable text, graph expansion from retrieved records, temporal filtering for current truth and point-in-time truth, and provenance-aware context assembly. Embeddings are retrieval indexes, not canonical memory.

## Temporal Semantics

Memorable must support both current-state and point-in-time questions. Agents should be able to ask what is true now, what was true before, what changed, and why.

The product should make temporal change explicit. Completing work, superseding decisions, correcting evidence, and replacing rules should preserve history rather than erasing it.

## Project Memory Profiles

Different projects deserve different memory shapes.

A software project may define concepts like component, module, API, architecture decision, bug, deployment, benchmark, dependency, and open question.

A work project may define concepts like meeting, commitment, document, stakeholder, follow-up, decision, risk, and status update.

A training project may define concepts like athlete profile, race, season plan, training phase, workout plan, workout event, measurement, rule, risk signal, weekly review, and action item.

Profiles should evolve. Agents can propose additions when they repeatedly see the same shape of memory. Humans approve profile changes.

## Agent Experience

Agents should interact with Memorable through explicit tools for writing, searching, reviewing, correcting, and generating views of memory.

Agents may write memory automatically when something is worth remembering, subject to the project's write policy. Sensitive categories can require suggestion or confirmation.

Agent retrieval should combine semantic similarity, graph context, temporal semantics, and provenance so returned context is both relevant and explainable.

## Review And Correction

Memory review is a first-class workflow.

Users and agents should be able to inspect what was remembered, why it was remembered, what is current, what is stale, and how to correct it. Automatic memory is only trustworthy when it is inspectable and correctable.

## Local-First Trust Posture

Memory belongs to the workspace and the human.

Local storage is the default. Cloud or remote storage can be supported, but it must be an explicit configuration choice. Memorable should not hide sync, ingestion, or remote persistence from the user.

## Non-Goals For The First Version

- Do not build a general note-taking app.
- Do not make passive workspace ingestion the default.
- Do not make Markdown the canonical memory store.
- Do not require a perfect schema before memory can start.
- Do not silently evolve project schemas without human approval.
- Do not rely on hidden LLM extraction or contradiction handling as the primary write policy.
- Do not treat all projects as software projects.
