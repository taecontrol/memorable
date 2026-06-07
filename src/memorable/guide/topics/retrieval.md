# Retrieval

Choose retrieval by the question you need answered.

Use `memorable_search_memory` for GraphRAG similarity: "what memory is relevant to this problem?" It takes `space`, `query`, `mode`, optionally `as_of`, optionally `record_type` to filter by Record Subtype, and optionally `attributes` to filter Entities by declared Attribute equality; it combines semantic search, graph expansion, temporal filtering, and provenance-aware explanations. Search finds useful candidates, not complete state lists. In the CLI, `memorable search --type FollowUp` filters by Record Subtype, and `memorable search --attr medium=video` filters by Attribute. Attributes appear in search results for matching Entities.

Use `memorable_reindex_space` after upgrading or changing Embedding settings to backfill derived Embeddings before search. If search reports no compatible Embeddings, run `memorable_doctor` and then reindex the MemorySpace.

Use `memorable_list_records` for Memory Review and state questions: "what is open?", "what did we create this week?", "which records are about this Entity?" Pass `space`, then filter with `type` for the kernel kind, `record_type` for a Record Subtype such as `GeneralObservation` or `FollowUp`, `state`, `since`, `until`, `about`, and `limit`. It deterministically lists Decisions, Observations, Relations, and Tasks; it does not list Entities. In the CLI, `memorable list --type FollowUp` filters by Record Subtype and `--record-kind task` filters by kernel kind.

Use `memorable_current_truth` when you already know a temporal record id and need the active version after supersession. Pass `space`, `record_id`, `record_kind` for a Decision, Observation, or Relation, and optionally `record_subtype` to filter by Record Subtype. In the CLI, `memorable truth current --type ArchitectureDecision` filters by Record Subtype.

Use `memorable_point_in_time_truth` when you already know a temporal record id and need what was valid at a historical time. Pass `space`, `record_id`, `record_kind`, `at`, and optionally `record_subtype` for the point you are reconstructing. In the CLI, `memorable truth as-of --type ArchitectureDecision` filters by Record Subtype.

Do not answer state questions with semantic search when a deterministic surface exists. Search is for relevance; `memorable_list_records` is for review lists; current truth and point-in-time truth are for resolving a known record through temporal history.
