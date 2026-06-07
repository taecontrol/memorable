# Reference

Every Memorable MCP tool in the current surface.

Writable Record Types: Decision, Observation, Task.

- `memorable_guide`: Read this guide; omit `topic` for the index or choose a guide topic.
- `memorable_status`: Return current Memorable service diagnostics for the MemorySpace scope.
- `memorable_doctor`: Run runtime health checks and return remediation hints.
- `memorable_init_space`: Initialize a MemorySpace from `.memorable/memory.yaml`.
- `memorable_inspect_space`: Inspect a MemoryProfile without initializing the MemorySpace.
- `memorable_remember_entity`: Remember an Entity with provenance, Validity Time, and optional declared Attributes via `attributes`.
- `memorable_remember_decision`: Remember a Decision, optionally setting a declared Record Subtype, superseding an earlier Decision, or linking About Entities.
- `memorable_remember_observation`: Remember an Observation, optionally setting a declared Record Subtype, superseding an earlier Observation, or linking About Entities.
- `memorable_remember_relation`: Remember a directed Relation between two Entities.
- `memorable_current_truth`: Resolve the active version of a known temporal record, optionally filtering by Record Subtype.
- `memorable_point_in_time_truth`: Resolve what a known temporal record said at a historical time, optionally filtering by Record Subtype.
- `memorable_inspect_history`: Inspect the supersession and lifecycle history for a temporal record; `record_kind` selects the kernel kind and history items return `record_type` as Record Subtype.
- `memorable_inspect_provenance`: Inspect provenance for a remembered Entity.
- `memorable_remember_task`: Remember a Task with lifecycle state, optionally setting a declared Record Subtype or linking About Entities.
- `memorable_complete_task`: Mark a Task completed at a Validity Time.
- `memorable_reindex_space`: Backfill persistent Embeddings for a MemorySpace.
- `memorable_search_memory`: Search memory by GraphRAG similarity with temporal filtering, optional Record Subtype filtering, and optional declared Attribute equality filtering.
- `memorable_inspect_task`: Inspect a Task's current or point-in-time lifecycle state.
- `memorable_list_records`: List MemoryRecords deterministically for Memory Review and state questions, optionally filtering by declared Record Subtype.
- `memorable_invalidate`: Mark a temporal record invalidated without a successor.
- `memorable_correct`: Correct a mistaken record statement or About membership.
- `memorable_forget_record`: Forget (hard-delete) a scratch MemoryRecord by id; refuses on a supersession chain.
- `memorable_forget_entity`: Forget (hard-delete) an Entity by id, cascading to its Relations and About links.
