# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Role                       | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

## Kind Labels

These labels are not triage states. They describe how an issue participates in planning/execution.

| Kind    | Label in our tracker | Meaning                                                |
| ------- | -------------------- | ------------------------------------------------------ |
| PRD     | `PRD`                | Planning parent; never an AFK implementation assignment |
| Slice   | `slice`              | Implementation slice that may be assigned to an agent  |

Queue rule: AFK workers may only pick issues with both `slice` and `ready-for-agent`, scoped to the current parent PRD, with all `## Blocked by` references closed. Never queue an issue labeled `PRD`.
