import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { createGhIssueViewTool } from "./tools/gh-issue-view.ts";
import { createGhPrCreateTool } from "./tools/gh-pr-create.ts";
import { createGhRunInspectTool } from "./tools/gh-run-inspect.ts";
import { createGitBranchCreateTool } from "./tools/git-branch-create.ts";
import { createGitCommitTool } from "./tools/git-commit.ts";
import { createGitInspectTool } from "./tools/git-inspect.ts";
import { createGitPushTool } from "./tools/git-push.ts";
import { createGitRestoreTool } from "./tools/git-restore.ts";

const WRITE_TOOLS = new Set(["git_branch_create", "git_commit", "git_push", "git_restore", "gh_pr_create"]);

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (!WRITE_TOOLS.has(event.toolName)) return undefined;

		const summary = summarizeInput(event.input);
		if (!ctx.hasUI) {
			return { block: true, reason: `repo-tools blocked ${event.toolName}; write tools require interactive approval.` };
		}

		const ok = await ctx.ui.confirm(
			`Confirm repo write: ${event.toolName}`,
			`repo-tools is about to run a git/GitHub write operation.\n\nTool: ${event.toolName}\nArguments:\n${summary}\n\nAllow?`,
		);
		if (!ok) return { block: true, reason: "Blocked by user" };
		return undefined;
	});

	// Read-only tools.
	pi.registerTool(createGitInspectTool(pi));
	pi.registerTool(createGhIssueViewTool(pi));
	pi.registerTool(createGhRunInspectTool(pi));

	// Write/network mutation tools; gated above via tool_call.
	pi.registerTool(createGitBranchCreateTool(pi));
	pi.registerTool(createGitCommitTool(pi));
	pi.registerTool(createGitPushTool(pi));
	pi.registerTool(createGitRestoreTool(pi));
	pi.registerTool(createGhPrCreateTool(pi));
}

function summarizeInput(input: unknown): string {
	let text: string;
	try {
		text = JSON.stringify(input, null, 2);
	} catch {
		text = String(input);
	}
	if (text.length <= 2_000) return text;
	return `${text.slice(0, 2_000)}\n... [truncated]`;
}
