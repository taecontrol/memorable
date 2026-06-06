# Writing

Pick the record type by what the memory means, not by convenience.

Use a Decision for a choice that should guide future behavior, design, product direction, or workflow. Write it with `memorable_remember_decision`, naming `space`, `decision_id`, `statement`, `source`, and `at`; set `supersedes` only when this Decision replaces an earlier one. If the MemoryProfile declares a Record Subtype that `extends: Decision`, pass `record_type` to tag the Decision with that subtype, such as `ArchitectureDecision`.

Use an Observation for an assertion worth remembering that is not a Decision, Task, or Relation. Write it with `memorable_remember_observation`, naming `space`, `observation_id`, `statement`, `source`, and `at`. If the MemoryProfile declares a Record Subtype that `extends: Observation`, pass `record_type` to tag the Observation with that subtype, such as `Episode` or `Pattern`. Observation is the flexible fallback, not the default for everything.

Use a Task for a commitment, follow-up, or piece of work with a lifecycle. Write it with `memorable_remember_task`, naming `space`, `task_id`, `title`, `source`, and `at`; pass `record_type` when the MemoryProfile declares a Record Subtype that `extends: Task`, such as `Commitment` or `FollowUp`; later use `memorable_complete_task` instead of deleting it.

Use an Entity for a remembered thing with identity inside the MemorySpace. Create it first with `memorable_remember_entity`, using `space`, `entity_id`, `entity_type`, `name`, `source`, and `at`. `entity_type` must be declared in the MemoryProfile.

When the Entity type declares Attributes, set durable Attribute values with the MCP `attributes` parameter, for example `attributes={"url": "https://example.test", "medium": "video", "published_on": "2026-06-06", "aliases": ["demo"]}`. In the CLI, pass repeatable `--attr name=value` flags: `memorable remember entity --type Reference --attr medium=video --attr published_on=2026-06-06`. `number` and `date` values are coerced from strings; repeat the same Attribute name for `list[string]`, or pass `--attr aliases=[]` for an empty list. Omit Attributes you do not know; all declared Attributes are optional, and re-remembering an Entity without Attributes does not wipe existing Attributes.

Use a Relation for a directed, truth-bearing connection between two Entities. Write it with `memorable_remember_relation`, naming `space`, `relation_id`, `source_entity_id`, `target_entity_id`, `relation_type`, `statement`, `source`, and `at`. A Relation connects Entity to Entity and can be superseded, corrected, or invalidated.

Use About when a record concerns one or more Entities. Pass existing Entity ids in `about` on `memorable_remember_decision`, `memorable_remember_observation`, or `memorable_remember_task`. About staples a record to Entities for retrieval and Memory Review; it is membership, not a truth-bearing Relation.

Do not try to write Evidence, Measurement, Event, or DerivedMemory yet. They are kernel vocabulary, not Writable Record Types in the current build, and are not valid `extends` targets. Use Observation as the fallback until those types gain write paths.
