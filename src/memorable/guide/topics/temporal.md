# Temporal

Memorable changes memory without erasing history. Pick the lifecycle operation by what happened.

Use supersession when the old record was true or useful, but a newer record now replaces, refines, or contradicts it. Write the new Decision, Observation, or Relation in the same `space` with `supersedes` set to the prior id. The old record becomes superseded; `memorable_current_truth` follows to the replacement, while `memorable_point_in_time_truth` can still reconstruct the earlier state.

Use correction when the old record was wrong, misleading, or stapled to the wrong Entity. Call `memorable_correct` with `space`, `record_kind`, `record_id`, `source`, `at`, and either `new_statement`, `about`, or both. Correction fixes the existing record instead of creating a ghost version that was never true.

Use invalidation when a claim stopped being true and there is no successor. Call `memorable_invalidate` with `space`, `record_kind`, `record_id`, and `at`; the record becomes invalidated and gains an Invalidation Time.

Use task completion when work is done. Call `memorable_complete_task` with `space`, `task_id`, and `at`; completion is a lifecycle transition, not deletion and not a writable Event record.

Validity Time is when the remembered claim, state, or commitment became true or applicable. Creation Time is when Memorable stored it. On `memorable_remember_*` calls, set `at` to the Validity Time, not automatically to now. If you store today's memory about a decision made last week, `at` should be last week.

For lifecycle transitions, `at` names when the transition became true: the replacement became valid, the claim stopped applying, or the task was completed. Use `memorable_point_in_time_truth` with the question's historical time, not the time you are asking the question.
