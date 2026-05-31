# Profiles

A MemoryProfile is the project-specific schema for one MemorySpace. Its first representation is `.memorable/memory.yaml`; create the scaffold as the Human Owner with `memorable init`, then inspect it through MCP with `memorable_inspect_space`.

The current profile schema is intentionally small. Top level keys are `version`, `space`, `entities`, `relations`, and `records`. `space` names the MemorySpace and may describe it. `entities` declares valid Entity types for `memorable_remember_entity`; `relations` declares valid Relation types for `memorable_remember_relation`; `records` declares project-specific MemoryRecord names.

Each declaration needs `name` and may include `description`. A record declaration also needs `extends`. In the current build, `extends` may name only a Writable Record Type: Decision, Observation, or Task. Evidence, Measurement, Event, DerivedMemory, MemoryRecord, Entity, and Relation are not valid `extends` targets.

Profile validation fails loudly. Unknown keys, target-design keys not parsed yet, missing `extends`, and extending a non-writable type are rejected when the profile loads. If a write fails because an `entity_type`, `relation_type`, or custom `record_type` is unknown, make it valid by editing `.memorable/memory.yaml` under the matching declaration and initializing or reloading that MemorySpace.

Do not use the profile as a generic preference file. It declares the project memory shape Memorable can enforce today; unsupported ideas belong in normal project docs until the profile schema grows.
