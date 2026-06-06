# Recipes

Record and later revise a Decision: call `memorable_remember_decision` with `space`, `decision_id`, `statement`, `source`, and Validity Time in `at`. When the choice is replaced, write a new Decision with a new `decision_id` and set `supersedes` to the prior id. Use `memorable_current_truth` with `record_kind` decision to resolve the active version, optionally `record_subtype` to scope it; use `memorable_inspect_history` when you need the chain.

Track a Task to completion: call `memorable_remember_task` with `space`, `task_id`, `title`, `source`, and `at` when the commitment becomes true. When the work is done, call `memorable_complete_task` with the same `space`, `task_id`, and completion time in `at`. Do not delete or rewrite the Task; completion is its lifecycle transition.

Answer "what's open this week?": use Memory Review, not semantic search. Call `memorable_list_records` with `space`, `state` open, and a `since`/`until` Creation Time window for the week. Add `type` task if you only want Tasks, or omit it to include all reviewable record types.

Attach records to an Entity and review by that Entity: first create the Entity with `memorable_remember_entity`, using a declared `entity_type`. Then pass its id in `about` when writing a Decision, Observation, or Task. Later call `memorable_list_records` with `about` set to that Entity id to review records stapled to it. Use a Relation only for a truth-bearing Entity-to-Entity claim, not for About membership.
