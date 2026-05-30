# Release Version Ladder

This is the release procedure for Memorable `0.0.x` packages.

## Scope

Use the `0.0.x` ladder while Memorable is proving the V1 install and acceptance flow. Every published patch must keep the clean-machine happy path healthy, but `0.0.x` does not promise stable command or tool output shapes yet.

## Patch-Level Changes

Acceptable `0.0.x` patch releases include:

- packaging, metadata, dependency, and Python baseline fixes;
- release workflow and acceptance-flow fixes;
- README, PyPI description, and documentation corrections;
- CLI or MCP bug fixes for existing V1 flows;
- expected CLI or MCP output shape changes while V1 interfaces settle;
- MemoryProfile scaffold corrections that keep first-run behavior coherent;
- narrow behavior refinements that preserve the V1 product promise.

Do not hide larger decisions in a patch release. Add or update an ADR before cutting a patch that changes storage strategy, temporal semantics, profile semantics, persisted data compatibility, or agent-facing interface direction.

## Cutting A `0.0.x` Release

1. Choose the next patch version, for example `0.0.2`.
2. Update `pyproject.toml` so `[project].version` equals that version.
3. Refresh version-bearing generated files if needed, for example `uv lock` when `uv.lock` records the project version.
4. Run the narrow release checks locally when available, then the normal lint and test suite.
5. Commit the version bump and any release-note or documentation updates.
6. Create an annotated or lightweight git tag named `v<version>`, for example `git tag v0.0.2`.
7. Verify the tag must match the package version: `v0.0.2` must correspond to `version = "0.0.2"` in `pyproject.toml`.
8. Push the commit, then push the tag: `git push origin main` and `git push origin v0.0.2`.
9. The tag-triggered release workflow publishes only after its pre-publish gates pass.
10. Confirm the post-publish sanity job installs the published artifact and passes its smoke check.

## Failure Rule

If the tag and `pyproject.toml` version differ, stop. Delete the local bad tag if it was not pushed, or cut a corrected new tag after the failed workflow makes the mismatch visible.
