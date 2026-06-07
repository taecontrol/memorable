# project-checks

Safe project-local validation tools for pi.

## Tools

- `run_tests` — fixed `uv run --extra dev pytest -q --color=no`
- `lint` — fixed `uv run --extra dev ruff check`

## Policy

- No raw command arguments.
- No shell execution.
- All commands run through `uv --extra dev`.
- `run_tests` targets must be under `tests/`.
- `run_tests` supports only `targets`, `marker`, `keyword`, `maxfail`, and `timeout_seconds`.
- `run_tests` marker expressions currently allow only the project marker `integration`.
- `lint` supports only validated paths, `fix`, and `timeout_seconds`.
- Nonzero pytest/ruff exits are normal tool results, not tool execution errors.
- Output is truncated to pi's built-in limits; full output is written to a temp file when truncated.
