import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { createGhIssueViewTool } from "./tools/gh-issue-view.ts";
import { createGhPrCreateTool } from "./tools/gh-pr-create.ts";
import { createGhRunInspectTool } from "./tools/gh-run-inspect.ts";
import { createGitBranchCreateTool } from "./tools/git-branch-create.ts";
import { createGitCommitTool } from "./tools/git-commit.ts";
import { createGitInspectTool } from "./tools/git-inspect.ts";
import { createGitPushTool } from "./tools/git-push.ts";
import { createGitRestoreTool } from "./tools/git-restore.ts";

export default function (pi: ExtensionAPI) {
	// Read-only tools.
	pi.registerTool(createGitInspectTool(pi));
	pi.registerTool(createGhIssueViewTool(pi));
	pi.registerTool(createGhRunInspectTool(pi));

	// AFK-safe write/network mutation tools. Safety comes from constrained argv,
	// validation, no force-push, no raw passthrough, and serialized git mutations.
	pi.registerTool(createGitBranchCreateTool(pi));
	pi.registerTool(createGitCommitTool(pi));
	pi.registerTool(createGitPushTool(pi));
	pi.registerTool(createGitRestoreTool(pi));
	pi.registerTool(createGhPrCreateTool(pi));
}
