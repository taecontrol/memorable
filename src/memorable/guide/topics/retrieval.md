# Retrieval

Choose retrieval by the question you need answered.

Use `memorable_search_memory` for GraphRAG similarity: "what memory is relevant to this problem?" It takes `space`, `query`, `mode`, and optionally `as_of`; it combines semantic search, graph expansion, temporal filtering, and provenance-aware explanations. Search finds useful candidates, not complete state lists.

Use `memorable_list_records` for Memory Review and state questions: "what is open?", "what did we create this week?", "which records are about this Entity?" Pass `space`, then filter with `type`, `state`, `since`, `until`, `about`, and `limit`. It deterministically lists Decisions, Observations, Relations, and Tasks; it does not list Entities.

Use `memorable_current_truth` when you already know a temporal record id and need the active version after supersession. Pass `space`, `record_id`, and `record_type` for a Decision, Observation, or Relation.

Use `memorable_point_in_time_truth` when you already know a temporal record id and need what was valid at a historical time. Pass `space`, `record_id`, `record_type`, and `at` for the point you are reconstructing.

Do not answer state questions with semantic search when a deterministic surface exists. Search is for relevance; `memorable_list_records` is for review lists; current truth and point-in-time truth are for resolving a known record through temporal history.
