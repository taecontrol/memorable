import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import {
	createAgentSession,
	DefaultResourceLoader,
	defineTool,
	getAgentDir,
	SessionManager,
	type AgentSession,
	type AgentSessionEvent,
	type ExtensionAPI,
	type ExtensionCommandContext,
	type ExtensionContext,
	type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import type {
	AgentManifest,
	AgentRole,
	AgentRoom,
	AgentStats,
	CreateRoomOptions,
	PrdRunMetadata,
	PrdSliceMetadata,
	PrdWorkflow,
	PullRequestMetadata,
	ResidentAgent,
	RoomManifest,
	RoomMessage,
	RoomStateEntry,
	SliceVerification,
	WorktreeInfo,
} from "./types.ts";
import {
	appendJsonl,
	ensureDir,
	mailboxPath,
	manifestPath,
	nowIso,
	readJson,
	readMailbox,
	runDir,
	runsRoot,
	writeJson,
} from "./storage.ts";
import { fitLine, oneLine, renderTile, truncate } from "./dashboard.ts";
import { execFile, git } from "./github.ts";
import { formatComments, issueBody, labelSet } from "./issues.ts";
import {
	AGENT_PROGRESS_INSTRUCTIONS,
	buildPrdArchitectPrompt,
	buildPrdImplementerPrompt,
	buildPrdReviewerPrompt,
	prdMetadata,
} from "./prompts.ts";
import { publishPrdPullRequest } from "./publish.ts";
import { allRoleNames, DEFAULT_ROLES, roleByName } from "./roles.ts";
import { loadPrdContext } from "./slices.ts";
import { currentPrdSlice, currentPrdSliceLabel, prdSliceLabel, prdWorkflow, setWorkflowPhase } from "./workflow.ts";

const STATE_TYPE = "agent-room-state";
const WIDGET_KEY = "agent-room";
const WORKTREES_DIR = [".pi", "agent-room", "worktrees"];
const HUMAN_NAME = "human";
const HUMAN_MESSAGE_TYPE = "agent-room-human-message";
const AGENT_ROOM_TOOL_NAMES = [
	"agent_send",
	"agent_broadcast",
	"agent_update",
	"agent_question",
	"agent_inbox",
	"agent_room_status",
	"agent_submit_review",
	"agent_finish_review",
	"agent_finish_architecture_review",
];
const TDD_SKILL_FILE = [".agents", "skills", "tdd", "SKILL.md"];

let activeRoom: AgentRoom | undefined;
let activeRunId: string | undefined;

function safeId(value: string): string {
	return value
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, 80);
}

function safeBranchPart(value: string): string {
	return (
		value
			.toLowerCase()
			.replace(/[^a-z0-9-]+/g, "-")
			.replace(/^-+|-+$/g, "")
			.slice(0, 48) || "room"
	);
}

function worktreesRoot(cwd: string): string {
	return path.join(cwd, ...WORKTREES_DIR);
}

function prdSlicePromptLabel(slice: PrdSliceMetadata): string {
	return prdSliceLabel(slice);
}

function prdSliceSubmitInstruction(slice: PrdSliceMetadata): string {
	return slice.synthetic === "final-architecture-fix"
		? "call agent_submit_review with the synthetic slice_number shown for this fix slice"
		: `call agent_submit_review for #${slice.number}`;
}

function buildPrdSliceAssignment(room: AgentRoom): string {
	const prd = room.manifest.prd;
	const workflow = prdWorkflow(room);
	if (!prd || !workflow) throw new Error("No PRD workflow is active.");
	const slice = currentPrdSlice(room);
	if (!slice) throw new Error("No current PRD slice is active.");
	const next = prd.orderedSlices[workflow.currentSliceIndex + 1];
	const blockers = slice.blockers.length ? slice.blockers.map((number) => `#${number}`).join(", ") : "none";
	return `# Current PRD slice assignment

PRD: #${prd.number} ${prd.title}
Current slice: ${prdSlicePromptLabel(slice)}
${slice.synthetic ? `Synthetic slice_number: ${slice.number}\n` : ""}URL: ${slice.url ?? "unknown"}
Blocked by: ${blockers}
Next slice after approval/commit/compact: ${next ? prdSlicePromptLabel(next) : "none"}

## Hard stop rules

- Implement exactly the current slice. Do not start, inspect, test, or plan the *next* slice.
- The blinder is about future slices, not existing contracts. Reading the existing code this slice touches — validation paths, public parameter names, invariants, and the read paths that resolve what you write — is required, not scope creep. A slice that adds a code path must satisfy the same invariants its sibling paths already enforce (converge on the same validation gate).
- When implementation verification is ready, ${prdSliceSubmitInstruction(slice)}, then stop.
- Do not continue because the reviewer is quiet. Continue only after AgentRoom sends a new slice assignment.
- Do not commit. AgentRoom commits approved slices after reviewer approval.
- Follow the required TDD skill for this slice.

## Slice test rules

- The room runs a mutation check on submit: it reverts your declared implFiles and the declared newTests must fail. A test that passes before its implementation exists, or that still passes once the implementation is reverted, is a defect — make it fail first (red), then implement.
- Assert lifecycle/temporal behavior through the resolved read path (current truth, point-in-time, or history), never by fetching a specific version with a repository get-by-id. A supersession test must assert on what the read path returns after supersession, not on the predecessor record.

${formatArchitectureConstraints(room)}## PRD context snapshot

${prd.context ?? `Ordered slices: ${prd.orderedSlices.map(prdSlicePromptLabel).join("; ")}`}

## Human-visible progress

${AGENT_PROGRESS_INSTRUCTIONS}`;
}

function buildPrdFinalArchitectPrompt(room: AgentRoom): string {
	const prd = room.manifest.prd;
	if (!prd) throw new Error("No PRD is active.");
	return `All ordered slices for PRD #${prd.number} ${prd.title} are approved and committed.

Run final architecture review of the branch/worktree. Review only; do not edit or commit. When complete, call agent_finish_architecture_review with approved or changes_requested so AgentRoom can publish or request a fix slice.

Committed slices: ${prd.orderedSlices.map(prdSlicePromptLabel).join(", ")}`;
}

function buildPrdFinalArchitectureFixPrompt(room: AgentRoom, findings: string, verification?: string): string {
	return `${buildPrdSliceAssignment(room)}

## Final architecture review changes requested

Fix the architecture blockers below. Do not broaden scope beyond these findings. Use TDD where code behavior changes. Re-run targeted probes plus full verification, then submit this synthetic fix slice for reviewer review.

Any new or corrected code path must satisfy the same invariants its sibling paths enforce: converge every branch on the shared validation gate rather than letting one branch bypass it. Read the existing validation/read paths you touch before changing them.

Findings:
${findings}

Architect verification:
${verification ?? "Not provided."}`;
}

function isFinalArchitectureBlockedReason(reason: string): boolean {
	return /^Final architecture review requested changes:/i.test(reason);
}

// --- Architecture constraint carry-over ---------------------------------------
// The architect broadcasts product/domain/temporal constraints once at kickoff.
// Those broadcasts are easily lost to per-slice tunnel vision and context
// compaction, so we persist them on the manifest and re-inject the relevant
// ones into every slice assignment (see buildPrdSliceAssignment).

function isArchitectureConstraintKind(kind: string): boolean {
	return /constraint|risk|architect|invariant|decision|guard|boundary|blocker|broadcast/i.test(kind);
}

function recordArchitectureConstraint(room: AgentRoom, kind: string, body: string): void {
	const trimmed = body.trim();
	if (!trimmed) return;
	const constraints = (room.manifest.architectureConstraints ??= []);
	if (constraints.some((existing) => existing.body === trimmed)) return;
	constraints.push({ kind, body: trimmed, at: nowIso() });
}

function formatArchitectureConstraints(room: AgentRoom): string {
	const constraints = room.manifest.architectureConstraints ?? [];
	if (constraints.length === 0) return "";
	const items = constraints.map((constraint) => `- (${constraint.kind}) ${constraint.body}`).join("\n");
	return `## Architecture constraints (carry into every slice)

These were broadcast by the architect for the whole PRD; they hold for this slice even if it is not where they were first raised. Honor them, and converge new code paths on the same invariants their siblings enforce.

${items}

`;
}

// --- Slice mutation check -----------------------------------------------------
// At submit time the implementer's slice changes are uncommitted in the worktree.
// We prove the declared behavior tests are not vacuous: they must PASS with the
// implementation present (green baseline), then FAIL once the declared impl files
// are reverted (red). The only fail-closed verdict is "vacuous" — green passes
// AND tests still pass with the implementation gone — which is runner-agnostic and
// the exact failure mode that slipped past review in PRD #206. Every other
// anomaly (no green baseline, git/stash/spawn trouble) is inconclusive and
// fails OPEN so infra hiccups never wedge a legitimate submit; the outcome is
// always surfaced to the reviewer in the review request.

const MUTATION_CHECK_TIMEOUT_MS = 10 * 60 * 1000;
const MUTATION_OUTPUT_TAIL = 2000;

type MutationCheckOutcome =
	| { status: "skipped"; message: string }
	| { status: "passed"; message: string }
	| { status: "vacuous"; message: string }
	| { status: "inconclusive"; message: string };

function errText(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function tailOutput(stdout: unknown, stderr: unknown): string {
	const combined = `${String(stdout ?? "")}${String(stderr ?? "")}`.trim();
	return combined.length > MUTATION_OUTPUT_TAIL ? `…${combined.slice(-MUTATION_OUTPUT_TAIL)}` : combined;
}

async function runBehaviorCommand(cwd: string, command: string): Promise<{ code: number; output: string }> {
	try {
		const result = await execFile("bash", ["-lc", command], {
			cwd,
			maxBuffer: 10 * 1024 * 1024,
			timeout: MUTATION_CHECK_TIMEOUT_MS,
		});
		return { code: 0, output: tailOutput(result.stdout, result.stderr) };
	} catch (error) {
		const err = error as { code?: number | string; stdout?: string; stderr?: string; killed?: boolean; message?: string };
		if (err.killed) throw new Error(`command timed out after ${MUTATION_CHECK_TIMEOUT_MS}ms: ${command}`);
		if (typeof err.code !== "number") throw new Error(`command could not run: ${err.message ?? String(error)}`);
		return { code: err.code, output: tailOutput(err.stdout, err.stderr) };
	}
}

async function stashRef(cwd: string): Promise<string> {
	try {
		return (await git(cwd, ["rev-parse", "--quiet", "--verify", "refs/stash"])).stdout.trim();
	} catch {
		return "";
	}
}

async function runSliceMutationCheck(room: AgentRoom, verification: SliceVerification): Promise<MutationCheckOutcome> {
	if (verification.newTests.length === 0) {
		return { status: "skipped", message: `No behavior test declared; reason: ${verification.noNewTestsReason ?? "none given"}.` };
	}
	if (verification.implFiles.length === 0) {
		return { status: "inconclusive", message: "No implFiles declared, so the implementation cannot be reverted to prove the tests fail (red)." };
	}

	let green: { code: number; output: string };
	try {
		green = await runBehaviorCommand(room.cwd, verification.command);
	} catch (error) {
		return { status: "inconclusive", message: `Could not run the verification command: ${errText(error)}` };
	}
	if (green.code !== 0) {
		return { status: "inconclusive", message: `Green baseline did not pass (exit ${green.code}); mutation check skipped.\n${green.output}` };
	}

	let stashed = false;
	try {
		const before = await stashRef(room.cwd);
		await git(room.cwd, ["stash", "push", "-u", "--", ...verification.implFiles]);
		stashed = (await stashRef(room.cwd)) !== before;
		if (!stashed) {
			return { status: "inconclusive", message: `Declared implFiles had no pending changes to revert: ${verification.implFiles.join(", ")}.` };
		}
		const red = await runBehaviorCommand(room.cwd, verification.command);
		if (red.code === 0) {
			return {
				status: "vacuous",
				message: `Tests still pass with the implementation reverted (${verification.implFiles.join(", ")}); they do not exercise this slice's behavior. Make them fail without the implementation, then resubmit.\n${red.output}`,
			};
		}
		return { status: "passed", message: `Mutation check passed: tests fail (exit ${red.code}) with ${verification.implFiles.join(", ")} reverted and pass once restored.` };
	} catch (error) {
		return { status: "inconclusive", message: `Mutation check could not complete: ${errText(error)}` };
	} finally {
		if (stashed) {
			await git(room.cwd, ["stash", "pop"]).catch((error) => {
				throw new Error(
					`Mutation check could not restore the implementation via 'git stash pop'; the changes are preserved in 'git stash'. Resolve manually before continuing. ${errText(error)}`,
				);
			});
		}
	}
}

function formatSliceVerification(verification: SliceVerification, mutation: MutationCheckOutcome): string {
	const tests = verification.newTests.length
		? verification.newTests.map((test) => `- ${test.file} :: ${test.name}`).join("\n")
		: `- none (${verification.noNewTestsReason ?? "no reason given"})`;
	const impl = verification.implFiles.length ? verification.implFiles.join(", ") : "none";
	return `Command: ${verification.command}
New behavior tests:
${tests}
Implementation files: ${impl}
Mutation check: ${mutation.status} — ${mutation.message}${verification.notes ? `\nNotes: ${verification.notes}` : ""}`;
}

function appendFinalArchitectureFixSlice(room: AgentRoom): PrdSliceMetadata {
	const prd = room.manifest.prd;
	const workflow = prdWorkflow(room);
	if (!prd || !workflow) throw new Error("No PRD workflow is active.");
	const ordinal = prd.orderedSlices.filter((slice) => slice.synthetic === "final-architecture-fix").length + 1;
	const slice: PrdSliceMetadata = {
		number: -ordinal,
		title: ordinal === 1 ? "Final architecture blocker fixes" : `Final architecture blocker fixes ${ordinal}`,
		blockers: [],
		synthetic: "final-architecture-fix",
	};
	prd.orderedSlices.push(slice);
	workflow.currentSliceIndex = prd.orderedSlices.length - 1;
	return slice;
}

async function requestFinalArchitectureFixSlice(
	room: AgentRoom,
	pi: ExtensionAPI,
	findings: string,
	verification: string | undefined,
	source: string,
): Promise<PrdSliceMetadata> {
	const prd = room.manifest.prd;
	if (!prd) throw new Error("No PRD workflow is active.");
	const slice = appendFinalArchitectureFixSlice(room);
	setWorkflowPhase(room, "implementing");
	await saveManifest(room);
	await routeMessage(
		room,
		source,
		HUMAN_NAME,
		`Final architecture review requested changes for PRD #${prd.number}; assigning ${prdSlicePromptLabel(slice)} to implementer.`,
		"architecture-changes-requested",
		pi,
	);
	await promptAgent(room, "implementer", buildPrdFinalArchitectureFixPrompt(room, findings, verification), true);
	return slice;
}

async function preparePrdBaseRef(cwd: string, options: CreateRoomOptions): Promise<CreateRoomOptions> {
	if (options.useWorktree === false || options.baseRef) return options;
	await git(cwd, ["fetch", "origin", "main"]);
	return { ...options, baseRef: "origin/main" };
}

async function createGitWorktree(controllerCwd: string, runId: string, name: string, baseRef = "HEAD"): Promise<WorktreeInfo> {
	await git(controllerCwd, ["rev-parse", "--show-toplevel"]);
	const workspacePath = path.join(worktreesRoot(controllerCwd), runId);
	const branch = `agent-room/${safeBranchPart(name)}-${randomUUID().slice(0, 8)}`;
	await ensureDir(path.dirname(workspacePath));
	await git(controllerCwd, ["worktree", "add", "-b", branch, workspacePath, baseRef]);
	return { path: workspacePath, branch, baseRef, createdAt: nowIso() };
}

function splitCommand(args: string): string[] {
	return args.trim().split(/\s+/).filter(Boolean);
}

function restoreActiveRun(ctx: ExtensionContext): string | undefined {
	let runId: string | undefined;
	for (const entry of ctx.sessionManager.getBranch() as RoomStateEntry[]) {
		if (entry.type !== "custom" || entry.customType !== STATE_TYPE) continue;
		runId = entry.data?.activeRunId ?? undefined;
	}
	return runId;
}

function persistActiveRun(pi: ExtensionAPI, runId: string | undefined): void {
	pi.appendEntry(STATE_TYPE, { activeRunId: runId ?? null });
}

function tddSkillPath(room: AgentRoom): string {
	return path.join(room.controllerCwd, ...TDD_SKILL_FILE);
}

function implementerTddInstructions(room: AgentRoom): string {
	const skillPath = tddSkillPath(room);
	return `# Required TDD skill

For implementation work, use the TDD skill at ${skillPath}.
- Before coding each implementation task or PRD slice, read ${skillPath}; resolve referenced docs relative to that skill directory.
- Follow vertical RED → GREEN → REFACTOR tracer bullets: one behavior test, confirm it fails, minimal code, confirm it passes, then next behavior.
- Do not batch all tests before implementation.
- Test observable behavior through public interfaces using Memorable domain language.
- A test that passes before its implementation exists is a defect: confirm the RED run fails for the intended reason before writing code. AgentRoom re-checks this on submit by reverting your implementation files.
- Assert lifecycle/temporal behavior through the resolved read path (current truth, point-in-time, history), never by fetching a specific version by id; a supersession test asserts on the read path's result after supersession, not on the predecessor record.
- AgentRoom no-commit policy overrides the skill's commit steps: do not commit unless explicitly instructed; report RED/GREEN evidence via agent_update and review requests instead.`;
}

function agentSystemPrompt(room: AgentRoom, role: AgentRole): string {
	const roleSpecificInstructions = role.name === "implementer" ? `\n\n${implementerTddInstructions(room)}` : "";
	return `${role.systemPrompt}${roleSpecificInstructions}

# AgentRoom

Room: ${room.name} (${room.id})
Your agent name: ${role.name}
Peers: ${allRoleNames().filter((name) => name !== role.name).join(", ")}
Working directory: ${room.cwd}
${room.manifest.worktree ? `Git worktree branch: ${room.manifest.worktree.branch}\nGit worktree path: ${room.manifest.worktree.path}` : "Workspace mode: current working tree"}

You are resident: your Pi session persists under ${relativeToCwd(room.controllerCwd, room.runDir)} and future prompts preserve your context.

Available AgentRoom tools:
- agent_update: send a visible update to the human/coordinator.
- agent_question: ask the human/coordinator for input; include choices when useful.
- agent_send: send a direct message to another resident agent, or to "human".
- agent_broadcast: send a message to all other resident agents.
- agent_submit_review: implementer submits the current PRD slice for review, then stops.
- agent_finish_review: reviewer submits the final verdict for the current PRD slice.
- agent_finish_architecture_review: architect submits the final branch verdict so AgentRoom can publish or block the PR.
- agent_inbox: inspect recent messages addressed to you.
- agent_room_status: inspect peer status.

When sending work to another agent or the human, include enough context for them to act without reading your mind.

Human-visible progress expectations:
${AGENT_PROGRESS_INSTRUCTIONS}`;
}

function buildCommunicationTools(room: AgentRoom, agentName: string, pi: ExtensionAPI): ToolDefinition[] {
	return [
		defineTool({
			name: "agent_send",
			label: "Agent Send",
			description: "Send a message to another persistent AgentRoom agent or to the human coordinator.",
			parameters: Type.Object({
				to: Type.String({ description: "Target agent name, or human" }),
				message: Type.String({ description: "Message body" }),
				kind: Type.Optional(Type.String({ description: "Message kind, e.g. review-request, finding, blocker, note" })),
			}),
			async execute(_toolCallId, params) {
				const result = await routeMessage(room, agentName, params.to, params.message, params.kind ?? "message", pi);
				return { content: [{ type: "text", text: result }], details: { to: params.to } };
			},
		}),
		defineTool({
			name: "agent_broadcast",
			label: "Agent Broadcast",
			description: "Broadcast a message to all other persistent AgentRoom agents.",
			parameters: Type.Object({
				message: Type.String({ description: "Message body" }),
				kind: Type.Optional(Type.String({ description: "Message kind" })),
			}),
			async execute(_toolCallId, params) {
				const targets = [...room.agents.keys()].filter((name) => name !== agentName);
				for (const target of targets) {
					await routeMessage(room, agentName, target, params.message, params.kind ?? "broadcast", pi);
				}
				return { content: [{ type: "text", text: `Broadcast sent to ${targets.join(", ") || "nobody"}.` }], details: { targets } };
			},
		}),
		defineTool({
			name: "agent_update",
			label: "Agent Update",
			description: "Send a short visible status update to the human/coordinator.",
			parameters: Type.Object({
				message: Type.String({ description: "Short human-visible update" }),
				kind: Type.Optional(Type.String({ description: "Update kind, e.g. progress, test, blocker, done" })),
			}),
			async execute(_toolCallId, params) {
				const result = await routeMessage(room, agentName, HUMAN_NAME, params.message, params.kind ?? "progress", pi);
				return { content: [{ type: "text", text: `${result} Use agent_question if you need a reply.` }], details: { to: HUMAN_NAME } };
			},
		}),
		defineTool({
			name: "agent_question",
			label: "Agent Question",
			description: "Ask the human/coordinator a question and wait for a reply via /room reply.",
			parameters: Type.Object({
				question: Type.String({ description: "Question for the human/coordinator" }),
				choices: Type.Optional(Type.Array(Type.String(), { description: "Optional choices" })),
			}),
			async execute(_toolCallId, params) {
				const body = params.choices?.length
					? `${params.question}\n\nChoices:\n${params.choices.map((choice: string, index: number) => `${index + 1}. ${choice}`).join("\n")}`
					: params.question;
				const result = await routeMessage(room, agentName, HUMAN_NAME, body, "question", pi);
				return { content: [{ type: "text", text: `${result} Stop now and wait for the human reply.` }], details: { to: HUMAN_NAME } };
			},
		}),
		defineTool({
			name: "agent_submit_review",
			label: "Agent Submit Review",
			description: "Implementer-only: submit the current PRD slice for reviewer verdict, then stop.",
			parameters: Type.Object({
				slice_number: Type.Optional(Type.Number({ description: "Current slice issue number" })),
				summary: Type.String({ description: "Implementation summary" }),
				files: Type.Optional(Type.Array(Type.String(), { description: "All changed files" })),
				verification: Type.Object(
					{
						command: Type.String({ description: "Command that runs this slice's behavior tests, e.g. 'uv run pytest path/to/test_x.py::test_y'" }),
						newTests: Type.Array(
							Type.Object({
								file: Type.String({ description: "Test file path, relative to repo root" }),
								name: Type.String({ description: "Test or behavior name" }),
							}),
							{ description: "New/changed behavior tests that prove this slice. Leave empty only with noNewTestsReason." },
						),
						implFiles: Type.Array(Type.String(), {
							description: "Non-test implementation files whose reversion must make newTests fail (the room reverts these to verify the tests are not vacuous).",
						}),
						noNewTestsReason: Type.Optional(
							Type.String({ description: "Required when newTests is empty: why no behavior test applies (e.g. pure refactor, docs, config)." }),
						),
						notes: Type.Optional(Type.String({ description: "Extra verification results for the reviewer" })),
					},
					{ description: "Structured verification; the room runs a mutation check (revert implFiles, newTests must fail) before routing to review." },
				),
			}),
			async execute(_toolCallId, params) {
				if (agentName !== "implementer") throw new Error("Only implementer may submit PRD slices for review.");
				const workflow = prdWorkflow(room);
				const slice = currentPrdSlice(room);
				if (!workflow || !slice) throw new Error("No active PRD slice to submit.");
				if (params.slice_number && params.slice_number !== slice.number) {
					throw new Error(`Current slice is #${slice.number}; refusing #${params.slice_number}.`);
				}
				const verification = params.verification as SliceVerification;
				if (verification.newTests.length === 0 && !verification.noNewTestsReason?.trim()) {
					throw new Error("Declare newTests for this slice, or set noNewTestsReason explaining why no behavior test applies.");
				}

				const mutation = await runSliceMutationCheck(room, verification);
				if (mutation.status === "vacuous") {
					// Fail closed: stay in implementing so the implementer can fix and resubmit.
					throw new Error(`Mutation check failed — ${mutation.message}`);
				}

				setWorkflowPhase(room, "reviewing");
				await saveManifest(room);
				const files = params.files?.length ? params.files.map((file: string) => `- ${file}`).join("\n") : "Not provided.";
				const body = `Review current PRD slice ${prdSliceLabel(slice)}.

Summary:
${params.summary}

Changed files:
${files}

Verification:
${formatSliceVerification(verification, mutation)}

Confirm the mutation-check result, the tests assert observable behavior through the resolved read path, and the slice's acceptance criteria. Return your final verdict with agent_finish_review. Do not start other work.`;
				await routeMessage(room, agentName, "reviewer", body, "review-request", pi);
				return {
					content: [
						{ type: "text", text: `Review requested for ${prdSliceLabel(slice)} (mutation check: ${mutation.status}). Stop now and wait for AgentRoom.` },
					],
					details: { slice: slice.number, status: "reviewing", mutation: mutation.status },
				};
			},
		}),
		defineTool({
			name: "agent_finish_review",
			label: "Agent Finish Review",
			description: "Reviewer-only: submit final current-slice verdict so AgentRoom can gate commit/next slice.",
			parameters: Type.Object({
				slice_number: Type.Optional(Type.Number({ description: "Reviewed slice issue number" })),
				status: Type.String({ description: "approved or changes_requested" }),
				findings: Type.String({ description: "Blocking/non-blocking findings or approval summary" }),
				verification: Type.Optional(Type.String({ description: "Reviewer verification commands/results" })),
			}),
			async execute(_toolCallId, params) {
				if (agentName !== "reviewer") throw new Error("Only reviewer may submit review verdicts.");
				const workflow = prdWorkflow(room);
				const slice = currentPrdSlice(room);
				if (!workflow || !slice) throw new Error("No active PRD slice to review.");
				if (params.slice_number && params.slice_number !== slice.number) {
					throw new Error(`Current slice is #${slice.number}; refusing verdict for #${params.slice_number}.`);
				}
				const status = params.status.trim().toLowerCase().replace(/[-\s]+/g, "_");
				if (status !== "approved" && status !== "changes_requested") throw new Error("status must be approved or changes_requested.");

				if (status === "changes_requested") {
					setWorkflowPhase(room, "implementing");
					await saveManifest(room);
					const body = `Review changes requested for ${prdSliceLabel(slice)}.

Findings:
${params.findings}

Reviewer verification:
${params.verification ?? "Not provided."}

Fix blockers for ${prdSliceLabel(slice)} only, then call agent_submit_review again. Do not start later slices.`;
					await routeMessage(room, agentName, "implementer", body, "review-findings", pi);
					return {
						content: [{ type: "text", text: `Changes requested for ${prdSliceLabel(slice)}; implementer queued after reviewer stops.` }],
						details: { slice: slice.number, status },
					};
				}

				setWorkflowPhase(room, "approved");
				if (!workflow.approvedSlices.includes(slice.number)) workflow.approvedSlices.push(slice.number);
				await saveManifest(room);
				await routeMessage(
					room,
					agentName,
					HUMAN_NAME,
					`Slice ${prdSliceLabel(slice)} approved. AgentRoom will commit, compact, then assign the next slice.`,
					"approved",
					pi,
				);
				return {
					content: [{ type: "text", text: `Approved ${prdSliceLabel(slice)}. Stop now; AgentRoom will commit and compact after this turn.` }],
					details: { slice: slice.number, status },
				};
			},
		}),
		defineTool({
			name: "agent_finish_architecture_review",
			label: "Agent Finish Architecture Review",
			description: "Architect-only: submit final branch verdict so AgentRoom can publish or block the PR.",
			parameters: Type.Object({
				status: Type.String({ description: "approved or changes_requested" }),
				findings: Type.String({ description: "Blocking findings or approval summary" }),
				verification: Type.Optional(Type.String({ description: "Final architecture verification commands/results" })),
			}),
			async execute(
				_toolCallId,
				params,
			): Promise<{
				content: Array<{ type: "text"; text: string }>;
				details: { status: string; pullRequest?: PullRequestMetadata };
			}> {
				if (agentName !== "architect") throw new Error("Only architect may finish final architecture review.");
				const workflow = prdWorkflow(room);
				const prd = room.manifest.prd;
				if (!workflow || !prd) throw new Error("No PRD workflow is active.");
				if (workflow.phase !== "final-reviewing" && workflow.phase !== "done") {
					throw new Error(`Final architecture review is not active; PRD workflow is ${workflow.phase}.`);
				}
				const status = params.status.trim().toLowerCase().replace(/[-\s]+/g, "_");
				if (status !== "approved" && status !== "changes_requested") {
					throw new Error("status must be approved or changes_requested.");
				}

				room.manifest.finalArchitectureReview = {
					status,
					findings: params.findings,
					verification: params.verification,
					reviewedAt: nowIso(),
				};

				if (status === "changes_requested") {
					const slice = await requestFinalArchitectureFixSlice(room, pi, params.findings, params.verification, agentName);
					return {
						content: [
							{
								type: "text",
								text: `Final architecture review requested changes. Assigned ${prdSliceLabel(slice)} to implementer. Stop now.`,
							},
						],
						details: { status },
					};
				}

				setWorkflowPhase(room, "publishing");
				await saveManifest(room);
				await routeMessage(room, agentName, HUMAN_NAME, `Final architecture review approved for PRD #${prd.number}. Publishing PR.`, "architecture-approved", pi);

				try {
					const pullRequest = await publishPrdPullRequest(room);
					room.manifest.pullRequest = pullRequest;
					setWorkflowPhase(room, "done");
					await saveManifest(room);
					await routeMessage(room, "agent-room", HUMAN_NAME, `PR ready for PRD #${prd.number}: ${pullRequest.url}`, "pr-ready", pi);
					return {
						content: [{ type: "text", text: `PR ready: ${pullRequest.url}` }],
						details: { status, pullRequest },
					};
				} catch (error) {
					const blockedReason = `PR publish failed: ${error instanceof Error ? error.message : String(error)}`;
					setWorkflowPhase(room, "blocked", { blockedReason });
					await saveManifest(room);
					await routeMessage(room, "agent-room", HUMAN_NAME, `PRD workflow blocked: ${blockedReason}`, "blocker", pi);
					throw error;
				}
			},
		}),
		defineTool({
			name: "agent_inbox",
			label: "Agent Inbox",
			description: "Read recent messages addressed to this agent.",
			parameters: Type.Object({
				limit: Type.Optional(Type.Number({ description: "Max messages to return" })),
			}),
			async execute(_toolCallId, params) {
				const limit = Math.max(1, Math.min(50, Math.floor(params.limit ?? 20)));
				const messages = room.messages.filter((message) => message.to === agentName).slice(-limit);
				const text = messages.length ? messages.map(formatMailboxMessage).join("\n\n") : "Inbox empty.";
				return { content: [{ type: "text", text }], details: { messages } };
			},
		}),
		defineTool({
			name: "agent_room_status",
			label: "Agent Room Status",
			description: "Show current status of all persistent AgentRoom agents.",
			parameters: Type.Object({}),
			async execute() {
				const rows = [...room.agents.values()].map((agent) => {
					const stats = agent.stats;
					return `- ${agent.role.name}: ${stats.status}, inbox ${stats.inbox}, turns ${stats.turns}, last: ${truncate(stats.lastMessage ?? "-")}`;
				});
				const workflow = prdWorkflow(room);
				const workflowText = workflow ? `\nworkflow: ${workflow.phase}, current ${currentPrdSliceLabel(room)}, queue ${room.promptQueue.length}` : "";
				return { content: [{ type: "text", text: `${rows.join("\n")}${workflowText}` }], details: { room: room.id } };
			},
		}),
	];
}

function formatMailboxMessage(message: RoomMessage): string {
	const reply = message.replyToId ? `\nReply-To: ${shortMessageId(message.replyToId)}` : "";
	return `From: ${message.from}\nKind: ${message.kind}\nAt: ${message.createdAt}${reply}\n\n${message.body}`;
}

function formatInboxPrompt(messages: RoomMessage[]): string {
	return `You received ${messages.length} AgentRoom message(s). Read them, update your persistent context, and act if requested.\n\n${messages
		.map(formatMailboxMessage)
		.join("\n\n---\n\n")}`;
}

async function createResidentAgent(room: AgentRoom, role: AgentRole, manifest: AgentManifest, pi: ExtensionAPI): Promise<ResidentAgent> {
	const sessionFile = path.isAbsolute(manifest.sessionFile)
		? manifest.sessionFile
		: path.resolve(room.controllerCwd, manifest.sessionFile);
	await ensureDir(path.dirname(sessionFile));
	const sessionManager = SessionManager.open(sessionFile, path.dirname(sessionFile), room.cwd);
	const resourceLoader = new DefaultResourceLoader({
		cwd: room.cwd,
		agentDir: getAgentDir(),
		additionalSkillPaths: role.name === "implementer" ? [tddSkillPath(room)] : [],
		noExtensions: true,
		noPromptTemplates: true,
		systemPromptOverride: (base) => `${base ?? ""}\n\n${agentSystemPrompt(room, role)}`,
	});
	await resourceLoader.reload();

	const { session } = await createAgentSession({
		cwd: room.cwd,
		resourceLoader,
		sessionManager,
		model: room.lastCtx?.model,
		thinkingLevel: pi.getThinkingLevel(),
		tools: [...role.tools, ...AGENT_ROOM_TOOL_NAMES],
		customTools: buildCommunicationTools(room, role.name, pi),
	});

	const stats = statsFromSession(session);
	const resident: ResidentAgent = { role, manifest, session, stats };
	resident.unsubscribe = session.subscribe((event) => handleAgentEvent(room, resident, event, pi));
	return resident;
}

function statsFromSession(session: AgentSession): AgentStats {
	const stats = session.getSessionStats();
	return {
		status: session.isStreaming ? "running" : "idle",
		turns: stats.assistantMessages,
		input: stats.tokens.input,
		output: stats.tokens.output,
		cost: stats.cost,
		inbox: 0,
		lastMessage: session.getLastAssistantText(),
	};
}

function handleAgentEvent(room: AgentRoom, agent: ResidentAgent, event: AgentSessionEvent, pi: ExtensionAPI): void {
	if (room.stopped) return;
	const stats = agent.stats;

	if (event.type === "agent_start") {
		stats.status = "running";
		stats.currentTask = "thinking";
		stats.error = undefined;
	}

	if (event.type === "tool_execution_start") {
		stats.status = "running";
		stats.currentTask = `tool: ${event.toolName}`;
		const workflow = prdWorkflow(room);
		if (shouldBlockImplementerTool(agent, workflow, event.toolName)) {
			void agent.session.abort();
			void routeMessage(
				room,
				"agent-room",
				HUMAN_NAME,
				`Blocked implementer tool ${event.toolName}; PRD workflow is ${workflow?.phase}.`,
				"workflow-guard",
				pi,
			);
		}
	}

	if (event.type === "message_update" && event.message?.role === "assistant") {
		const text = event.message.content.find((part) => part.type === "text")?.text;
		if (text) stats.lastMessage = truncate(text);
	}

	if (event.type === "agent_end") {
		const fresh = statsFromSession(agent.session);
		agent.stats = { ...fresh, inbox: pendingMessagesFor(room, agent.role.name).length };
		if (room.activeAgentName === agent.role.name) room.activeAgentName = undefined;
		updateDashboard(room);
		void afterAgentEnd(room, agent.role.name, pi);
		return;
	}

	if (event.type === "compaction_start") {
		stats.status = "running";
		stats.currentTask = "compacting";
	}

	if (event.type === "compaction_end") {
		stats.status = agent.session.isStreaming ? "running" : "idle";
		stats.currentTask = undefined;
	}

	updateDashboard(room);
}

function shouldBlockImplementerTool(agent: ResidentAgent, workflow: PrdWorkflow | undefined, toolName: string): boolean {
	if (agent.role.name !== "implementer" || !workflow || AGENT_ROOM_TOOL_NAMES.includes(toolName)) return false;
	return !["implementing", "publishing", "done"].includes(workflow.phase);
}

function pendingMessagesFor(room: AgentRoom, agentName: string): RoomMessage[] {
	const agent = room.agents.get(agentName);
	if (!agent) return [];
	const delivered = new Set(agent.manifest.deliveredMessageIds);
	return room.messages.filter((message) => message.to === agentName && !delivered.has(message.id));
}

function shortMessageId(id: string): string {
	return id.slice(0, 8);
}

function humanMessages(room: AgentRoom): RoomMessage[] {
	return room.messages.filter((message) => message.to === HUMAN_NAME);
}

function latestHumanMessage(room: AgentRoom): RoomMessage | undefined {
	return humanMessages(room).at(-1);
}

function findMessageByIdPrefix(room: AgentRoom, prefix: string): RoomMessage | undefined {
	const matches = room.messages.filter((message) => message.id === prefix || message.id.startsWith(prefix));
	if (matches.length > 1) throw new Error(`Ambiguous message id prefix: ${prefix}`);
	return matches[0];
}

function sendHumanVisibleMessage(pi: ExtensionAPI, room: AgentRoom, message: RoomMessage): void {
	const replyHint = `/room reply ${shortMessageId(message.id)} <answer>`;
	pi.sendMessage({
		customType: HUMAN_MESSAGE_TYPE,
		content: message.body,
		display: true,
		details: {
			roomId: room.id,
			roomName: room.name,
			messageId: message.id,
			from: message.from,
			kind: message.kind,
			createdAt: message.createdAt,
			replyHint,
		},
	});
}

async function routeMessage(
	room: AgentRoom,
	from: string,
	to: string,
	body: string,
	kind = "message",
	pi?: ExtensionAPI,
	replyToId?: string,
): Promise<string> {
	const isHumanTarget = to === HUMAN_NAME;
	const target = isHumanTarget ? undefined : room.agents.get(to);
	if (!isHumanTarget && !target) {
		return `Unknown recipient "${to}". Available: ${[...room.agents.keys(), HUMAN_NAME].join(", ")}`;
	}

	const workflow = prdWorkflow(room);
	if (workflow && from === "implementer" && to === "reviewer" && /review/i.test(kind) && workflow.phase === "implementing") {
		setWorkflowPhase(room, "reviewing");
		await saveManifest(room);
	}

	// Persist architect constraints so they survive compaction and can be re-injected
	// into every slice assignment, not just the slice in flight when they were raised.
	if (workflow && from === "architect" && !isHumanTarget && isArchitectureConstraintKind(kind)) {
		recordArchitectureConstraint(room, kind, body);
	}

	const message: RoomMessage = {
		id: randomUUID(),
		createdAt: nowIso(),
		from,
		to,
		kind,
		body,
		replyToId,
	};
	room.messages.push(message);
	await appendJsonl(room.mailboxPath, message);

	const source = room.agents.get(from);
	if (source) source.stats.lastMessage = truncate(`${kind}: ${body}`);

	if (isHumanTarget) {
		updateDashboard(room);
		if (pi) sendHumanVisibleMessage(pi, room, message);
		return `Message sent to ${HUMAN_NAME} (${shortMessageId(message.id)}).`;
	}

	target!.stats.inbox = pendingMessagesFor(room, to).length;
	updateDashboard(room);
	void deliverInbox(room, to);
	return `Message sent to ${to}.`;
}

async function afterAgentEnd(room: AgentRoom, agentName: string, pi: ExtensionAPI): Promise<void> {
	await saveManifest(room);
	await runPrdWorkflowAutomation(room, pi);
	await deliverInbox(room, agentName);
	pumpPromptQueue(room);
}

function anyAgentStreaming(room: AgentRoom): boolean {
	return [...room.agents.values()].some((agent) => agent.session.isStreaming);
}

function enqueuePrompt(room: AgentRoom, agentName: string, prompt: string, deliveredMessageIds: string[] = [], front = false): void {
	const agent = room.agents.get(agentName);
	if (!agent) throw new Error(`Unknown agent: ${agentName}`);
	const request = { id: randomUUID(), agentName, prompt, deliveredMessageIds };
	if (front) room.promptQueue.unshift(request);
	else room.promptQueue.push(request);
	agent.stats.status = "queued";
	agent.stats.currentTask = truncate(prompt, 80);
	updateDashboard(room);
	pumpPromptQueue(room);
}

function pumpPromptQueue(room: AgentRoom): void {
	if (room.stopped || room.automationActive || room.activeAgentName || anyAgentStreaming(room)) return;
	const request = room.promptQueue.shift();
	if (!request) {
		updateDashboard(room);
		return;
	}

	const agent = room.agents.get(request.agentName);
	if (!agent) {
		for (const id of request.deliveredMessageIds) room.queuedMessageIds.delete(id);
		pumpPromptQueue(room);
		return;
	}

	for (const id of request.deliveredMessageIds) {
		room.queuedMessageIds.delete(id);
		if (!agent.manifest.deliveredMessageIds.includes(id)) agent.manifest.deliveredMessageIds.push(id);
	}
	agent.stats.inbox = pendingMessagesFor(room, request.agentName).length;
	agent.stats.status = "running";
	agent.stats.currentTask = truncate(request.prompt, 80);
	room.activeAgentName = request.agentName;
	updateDashboard(room);

	void saveManifest(room)
		.then(() => agent.session.prompt(request.prompt, { source: "extension", expandPromptTemplates: false }))
		.catch((error: unknown) => {
			agent.stats.status = "error";
			agent.stats.error = error instanceof Error ? error.message : String(error);
			agent.stats.lastMessage = agent.stats.error;
			if (room.activeAgentName === request.agentName) room.activeAgentName = undefined;
			updateDashboard(room);
			pumpPromptQueue(room);
		});
}

async function deliverInbox(room: AgentRoom, agentName: string): Promise<void> {
	if (room.stopped) return;
	const agent = room.agents.get(agentName);
	if (!agent) return;

	const pending = pendingMessagesFor(room, agentName).filter((message) => !room.queuedMessageIds.has(message.id));
	if (pending.length === 0) {
		agent.stats.inbox = pendingMessagesFor(room, agentName).length;
		updateDashboard(room);
		return;
	}

	for (const message of pending) room.queuedMessageIds.add(message.id);
	agent.stats.inbox = pendingMessagesFor(room, agentName).length;
	enqueuePrompt(room, agentName, formatInboxPrompt(pending), pending.map((message) => message.id));
}

async function promptAgent(room: AgentRoom, agentName: string, prompt: string, front = false): Promise<void> {
	if (room.stopped) return;
	enqueuePrompt(room, agentName, prompt, [], front);
}

async function runPrdWorkflowAutomation(room: AgentRoom, pi: ExtensionAPI): Promise<void> {
	const workflow = prdWorkflow(room);
	if (!workflow || workflow.phase !== "approved" || room.automationActive || anyAgentStreaming(room)) return;
	const slice = currentPrdSlice(room);
	if (!slice) return;

	room.automationActive = true;
	try {
		setWorkflowPhase(room, "committing");
		await saveManifest(room);
		await routeMessage(room, "agent-room", HUMAN_NAME, `Committing approved slice ${prdSliceLabel(slice)}.`, "commit", pi);
		await commitCurrentSlice(room, slice);
		if (!workflow.committedSlices.includes(slice.number)) workflow.committedSlices.push(slice.number);

		setWorkflowPhase(room, "compacting");
		await saveManifest(room);
		await routeMessage(room, "agent-room", HUMAN_NAME, `Compacting agents after ${prdSliceLabel(slice)}.`, "compact", pi);
		const { deferred } = await compactResidentAgents(room, slice);
		if (deferred.length > 0) {
			await routeMessage(
				room,
				"agent-room",
				HUMAN_NAME,
				`Compaction deferred for ${deferred.join(", ")} after ${prdSliceLabel(slice)} (provider overloaded past retry budget); continuing without blocking. Context will compact on the next attempt.`,
				"compact-deferred",
				pi,
			);
		}

		workflow.currentSliceIndex += 1;
		const next = currentPrdSlice(room);
		if (next) {
			setWorkflowPhase(room, "implementing");
			await saveManifest(room);
			await routeMessage(
				room,
				"agent-room",
				HUMAN_NAME,
				`Slice ${prdSliceLabel(slice)} committed/compacted. Assigning ${prdSliceLabel(next)}.`,
				"next-slice",
				pi,
			);
			await promptAgent(room, "implementer", buildPrdSliceAssignment(room), true);
			return;
		}

		setWorkflowPhase(room, "final-reviewing");
		await saveManifest(room);
		await routeMessage(room, "agent-room", HUMAN_NAME, `All PRD slices committed/compacted; requesting final architecture review.`, "final-review", pi);
		await promptAgent(room, "architect", buildPrdFinalArchitectPrompt(room), true);
	} catch (error) {
		const blockedReason = error instanceof Error ? error.message : String(error);
		setWorkflowPhase(room, "blocked", { blockedReason });
		await saveManifest(room);
		await routeMessage(room, "agent-room", HUMAN_NAME, `PRD workflow blocked: ${blockedReason}`, "blocker", pi);
	} finally {
		room.automationActive = false;
		updateDashboard(room);
		pumpPromptQueue(room);
	}
}

async function commitCurrentSlice(room: AgentRoom, slice: PrdRunMetadata["orderedSlices"][number]): Promise<void> {
	const prd = room.manifest.prd;
	if (!prd) throw new Error("No PRD metadata available for commit.");
	const status = (await git(room.cwd, ["status", "--porcelain"])).stdout.trim();
	if (!status) return;
	await git(room.cwd, ["add", "-A"]);
	await git(room.cwd, [
		"commit",
		"-m",
		`Implement PRD #${prd.number} slice #${slice.number}`,
		"-m",
		`${slice.title}\n\nAgentRoom run: ${room.id}`,
	]);
}

// Compaction is an optimization (context trimming), not correctness. Normal agent
// turns auto-retry transient provider overload (HTTP 529) via the agent loop, but the
// compaction/summarization path has no built-in retry — a single overload throws.
// Rather than wedge the whole PRD workflow in "blocked", defer compaction for any agent
// whose overload outlasts the retry budget and let the workflow proceed; that agent's
// context compacts on the next attempt (or via auto-compaction during its next turn).
async function compactResidentAgents(
	room: AgentRoom,
	slice: PrdRunMetadata["orderedSlices"][number],
): Promise<{ deferred: string[] }> {
	const instructions = `Slice ${prdSliceLabel(slice)} was approved and committed. Preserve AgentRoom decisions, review verdicts, files changed, verification evidence, unresolved blockers, and the next assigned slice.`;
	const deferred: string[] = [];
	for (const agent of room.agents.values()) {
		if (agent.session.isStreaming) throw new Error(`Cannot compact while ${agent.role.name} is running.`);
		agent.stats.status = "running";
		agent.stats.currentTask = "compacting";
		updateDashboard(room);
		try {
			await compactWithRetry(agent.session, instructions);
		} catch (error) {
			if (!isOverloadedError(error)) throw error;
			deferred.push(agent.role.name);
		}
		const fresh = statsFromSession(agent.session);
		agent.stats = { ...fresh, inbox: pendingMessagesFor(room, agent.role.name).length };
		updateDashboard(room);
	}
	return { deferred };
}

// Overload incidents routinely outlast a few seconds, so spread retries across a few
// minutes (1,2,4,8,16,32,60,60s ≈ 3min) before giving up and deferring compaction.
const COMPACT_MAX_ATTEMPTS = 8;
const COMPACT_BACKOFF_BASE_MS = 1000;
const COMPACT_BACKOFF_CAP_MS = 60000;

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

// Compaction issues a model call (turn-prefix summarization) that can hit transient
// provider overload (HTTP 529). Unlike normal turns, this path has no built-in retry,
// so retry transient overloads with backoff here; on exhaustion the caller defers
// compaction instead of blocking the workflow.
async function compactWithRetry(session: AgentSession, instructions: string): Promise<void> {
	for (let attempt = 1; ; attempt += 1) {
		try {
			await session.compact(instructions);
			return;
		} catch (error) {
			if (isAlreadyCompactedError(error)) return;
			if (!isOverloadedError(error) || attempt >= COMPACT_MAX_ATTEMPTS) throw error;
			const backoff = Math.min(COMPACT_BACKOFF_CAP_MS, COMPACT_BACKOFF_BASE_MS * 2 ** (attempt - 1));
			const jitter = Math.floor(Math.random() * 500);
			await sleep(backoff + jitter);
		}
	}
}

function isAlreadyCompactedError(error: unknown): boolean {
	const message = error instanceof Error ? error.message : String(error);
	return /already compacted/i.test(message);
}

function isOverloadedError(error: unknown): boolean {
	const message = error instanceof Error ? error.message : String(error);
	return /overloaded_error|\boverloaded\b|\b529\b/i.test(message);
}


async function saveManifest(room: AgentRoom): Promise<void> {
	room.manifest.updatedAt = nowIso();
	room.manifest.agents = [...room.agents.values()].map((agent) => agent.manifest);
	await writeJson(room.manifestPath, room.manifest);
}

function relativeToCwd(cwd: string, filePath: string): string {
	const relative = path.relative(cwd, filePath);
	return relative.startsWith("..") ? filePath : relative;
}

async function createRoom(
	pi: ExtensionAPI,
	ctx: ExtensionCommandContext | ExtensionContext,
	name: string,
	options: CreateRoomOptions = {},
): Promise<AgentRoom> {
	const id = `${safeId(name || "room")}-${Date.now()}-${randomUUID().slice(0, 8)}`;
	const controllerCwd = ctx.cwd;
	const useWorktree = options.useWorktree ?? true;
	const worktree = useWorktree ? await createGitWorktree(controllerCwd, id, name || id, options.baseRef ?? "HEAD") : undefined;
	const workspaceCwd = worktree?.path ?? controllerCwd;
	const dir = runDir(controllerCwd, id);
	const sessionsDir = path.join(dir, "sessions");
	await ensureDir(sessionsDir);

	const manifest: RoomManifest = {
		id,
		name: name || id,
		cwd: workspaceCwd,
		controllerCwd,
		workspaceCwd,
		worktree,
		prd: options.prd,
		workflow: options.prd
			? { kind: "prd", currentSliceIndex: 0, phase: "implementing", approvedSlices: [], committedSlices: [] }
			: undefined,
		createdAt: nowIso(),
		updatedAt: nowIso(),
		agents: DEFAULT_ROLES.map((role) => {
			const sessionFile = path.join(sessionsDir, `${role.name}.jsonl`);
			return {
				name: role.name,
				title: role.title,
				description: role.description,
				sessionFile: relativeToCwd(controllerCwd, sessionFile),
				deliveredMessageIds: [],
			};
		}),
	};

	const room: AgentRoom = {
		id,
		name: manifest.name,
		cwd: workspaceCwd,
		controllerCwd,
		runDir: dir,
		manifestPath: manifestPath(dir),
		mailboxPath: mailboxPath(dir),
		manifest,
		messages: [],
		agents: new Map(),
		promptQueue: [],
		queuedMessageIds: new Set(),
		automationActive: false,
		lastCtx: ctx,
		stopped: false,
	};

	await writeJson(room.manifestPath, manifest);
	for (const agentManifest of manifest.agents) {
		const role = roleByName(agentManifest.name);
		if (!role) continue;
		const agent = await createResidentAgent(room, role, agentManifest, pi);
		room.agents.set(role.name, agent);
	}
	await saveManifest(room);
	return room;
}

async function loadRoom(pi: ExtensionAPI, ctx: ExtensionCommandContext | ExtensionContext, runId: string): Promise<AgentRoom> {
	const dir = runDir(ctx.cwd, runId);
	const manifest = await readJson<RoomManifest>(manifestPath(dir));
	if (!manifest) throw new Error(`No AgentRoom manifest found for ${runId}.`);

	const controllerCwd = manifest.controllerCwd ?? ctx.cwd;
	const workspaceCwd = manifest.workspaceCwd ?? manifest.cwd ?? ctx.cwd;
	if (manifest.prd && !manifest.workflow) {
		manifest.workflow = { kind: "prd", currentSliceIndex: 0, phase: "implementing", approvedSlices: [], committedSlices: [] };
	}
	const room: AgentRoom = {
		id: manifest.id,
		name: manifest.name,
		cwd: workspaceCwd,
		controllerCwd,
		runDir: dir,
		manifestPath: manifestPath(dir),
		mailboxPath: mailboxPath(dir),
		manifest,
		messages: await readMailbox(mailboxPath(dir)),
		agents: new Map(),
		promptQueue: [],
		queuedMessageIds: new Set(),
		automationActive: false,
		lastCtx: ctx,
		stopped: false,
	};

	for (const agentManifest of manifest.agents) {
		const role = roleByName(agentManifest.name);
		if (!role) continue;
		const agent = await createResidentAgent(room, role, agentManifest, pi);
		agent.stats.inbox = pendingMessagesFor(room, role.name).length;
		room.agents.set(role.name, agent);
	}
	return room;
}

async function disposeRoom(room: AgentRoom | undefined): Promise<void> {
	if (!room) return;
	room.stopped = true;
	for (const agent of room.agents.values()) {
		agent.unsubscribe?.();
		agent.session.dispose();
	}
	await saveManifest(room);
}

async function removeAgentRoomWorktree(controllerCwd: string, worktreePath: string, force: boolean): Promise<void> {
	try {
		await fs.access(worktreePath);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") {
			await git(controllerCwd, ["worktree", "prune"]);
			return;
		}
		throw error;
	}

	const args = ["worktree", "remove", ...(force ? ["--force"] : []), worktreePath];
	await git(controllerCwd, args);
}

function parseDestroyArgs(args: string[]): { runId?: string; force: boolean } {
	let runId: string | undefined;
	let force = false;
	for (const arg of args) {
		if (arg === "--force" || arg === "-f") {
			force = true;
			continue;
		}
		if (!runId) {
			runId = arg;
			continue;
		}
		throw new Error(`Unexpected destroy argument: ${arg}`);
	}
	return { runId, force };
}

async function destroyRoom(pi: ExtensionAPI, ctx: ExtensionCommandContext, args: string[]): Promise<void> {
	const { runId, force } = parseDestroyArgs(args);
	const targetRunId = runId ?? activeRoom?.id;
	if (!targetRunId) throw new Error("Usage: /agent-room destroy [run-id] [--force]");

	const activeTarget = activeRoom?.id === targetRunId ? activeRoom : undefined;
	const initialRunDir = runDir(ctx.cwd, targetRunId);
	const manifest = activeTarget?.manifest ?? (await readJson<RoomManifest>(manifestPath(initialRunDir)));
	if (!manifest) throw new Error(`No AgentRoom manifest found for ${targetRunId}.`);

	const controllerCwd = manifest.controllerCwd ?? ctx.cwd;
	const targetRunDir = activeTarget?.runDir ?? runDir(controllerCwd, targetRunId);
	const worktreePath = manifest.worktree?.path;
	const worktreeLabel = worktreePath ? relativeToCwd(controllerCwd, worktreePath) : "none (in-place run)";

	if (!force) {
		if (!ctx.hasUI) throw new Error("Destroy requires confirmation; rerun with --force to skip confirmation.");
		const confirmed = await ctx.ui.confirm(
			"Destroy AgentRoom?",
			[
				`Run: ${targetRunId}`,
				`State: ${relativeToCwd(controllerCwd, targetRunDir)}`,
				`Worktree: ${worktreeLabel}`,
				"This deletes resident sessions, mailbox, manifest, and the AgentRoom worktree.",
			].join("\n"),
		);
		if (!confirmed) {
			ctx.ui.notify("AgentRoom destroy cancelled.", "info");
			return;
		}
	}

	if (activeTarget) {
		await disposeRoom(activeTarget);
		activeRoom = undefined;
		activeRunId = undefined;
		persistActiveRun(pi, undefined);
		clearDashboard(ctx);
	}
	if (worktreePath) {
		try {
			await removeAgentRoomWorktree(controllerCwd, worktreePath, force);
		} catch (error) {
			const suffix = force ? "" : ` Rerun /agent-room destroy ${targetRunId} --force to discard dirty worktree changes.`;
			throw new Error(`Failed to remove AgentRoom worktree: ${error instanceof Error ? error.message : String(error)}.${suffix}`);
		}
	}
	await fs.rm(targetRunDir, { recursive: true, force: true });

	if (activeRunId === targetRunId) {
		activeRunId = undefined;
		persistActiveRun(pi, undefined);
	}

	ctx.ui.notify(`Destroyed AgentRoom ${targetRunId}.`, "info");
}

async function activateRoom(pi: ExtensionAPI, ctx: ExtensionCommandContext | ExtensionContext, room: AgentRoom): Promise<void> {
	await disposeRoom(activeRoom);
	activeRoom = room;
	activeRunId = room.id;
	persistActiveRun(pi, room.id);
	updateDashboard(room, ctx);
}

async function listRooms(cwd: string): Promise<RoomManifest[]> {
	const root = runsRoot(cwd);
	try {
		const entries = await fs.readdir(root, { withFileTypes: true });
		const manifests: RoomManifest[] = [];
		for (const entry of entries) {
			if (!entry.isDirectory()) continue;
			const manifest = await readJson<RoomManifest>(manifestPath(path.join(root, entry.name)));
			if (manifest) manifests.push(manifest);
		}
		return manifests.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
		throw error;
	}
}

function updateDashboard(room = activeRoom, ctx = room?.lastCtx): void {
	if (!room || !ctx?.hasUI) return;
	room.lastCtx = ctx;
	ctx.ui.setWidget(
		WIDGET_KEY,
		(_tui: unknown, theme: any) => ({
			render(width: number) {
				return renderTiles(room, width, theme);
			},
			invalidate() {},
		}),
		{ placement: "aboveEditor" },
	);
}

function clearDashboard(ctx: ExtensionContext | ExtensionCommandContext): void {
	if (!ctx.hasUI) return;
	ctx.ui.setWidget(WIDGET_KEY, undefined);
}

function renderTiles(room: AgentRoom, width: number, theme: any): string[] {
	const safeWidth = Math.max(0, Math.floor(width));
	const agents = [...room.agents.values()];
	if (agents.length === 0 || safeWidth === 0) return [];
	const gap = 2;
	const columns = Math.max(1, Math.min(3, Math.floor((safeWidth + gap) / 34), agents.length));
	const tileWidth = Math.max(1, Math.floor((safeWidth - gap * (columns - 1)) / columns));
	const rows: string[] = [];
	rows.push(theme.fg("accent", fitLine(`AgentRoom ${room.name} (${room.id})`, safeWidth, "…")));
	if (room.manifest.prd) {
		const prd = room.manifest.prd;
		const slices = prd.orderedSlices.map(prdSlicePromptLabel).join(" → ");
		rows.push(theme.fg("muted", fitLine(`PRD #${prd.number}: ${prd.title} | slices: ${slices || "none"}`, safeWidth, "…")));
		const workflow = prdWorkflow(room);
		if (workflow) {
			rows.push(theme.fg("muted", fitLine(`workflow: ${workflow.phase} | current: ${currentPrdSliceLabel(room)} | queue: ${room.promptQueue.length}`, safeWidth, "…")));
		}
		if (room.manifest.pullRequest) {
			rows.push(theme.fg("muted", fitLine(`PR #${room.manifest.pullRequest.number}: ${room.manifest.pullRequest.url}`, safeWidth, "…")));
		}
	}
	const humanMessage = latestHumanMessage(room);
	if (humanMessage) {
		rows.push(theme.fg("warning", fitLine(`Human msg ${shortMessageId(humanMessage.id)} from ${humanMessage.from}: ${oneLine(humanMessage.body)}`, safeWidth, "…")));
	}

	for (let i = 0; i < agents.length; i += columns) {
		const group = agents.slice(i, i + columns).map((agent, index) => renderTile(agent, tileWidth, theme, i + index));
		const height = Math.max(...group.map((tile) => tile.length));
		for (let line = 0; line < height; line += 1) {
			rows.push(group.map((tile) => tile[line] ?? " ".repeat(tileWidth)).join(" ".repeat(gap)));
		}
	}
	return rows.map((line) => fitLine(line, safeWidth));
}

function requireRoom(): AgentRoom {
	if (!activeRoom) throw new Error("No active AgentRoom. Run /agent-room start first.");
	return activeRoom;
}

function usage(): string {
	return [
		"Usage:",
		"/agent-room start [--in-place] [--base <ref>] [name]",
		"/agent-room prd [--in-place] [--base <ref>] <issue-or-url>",
		"/agent-room resume <run-id>",
		"/agent-room unblock [run-id]",
		"/agent-room list",
		"/agent-room status",
		"/agent-room ask <agent|all> <message>",
		"/agent-room reply <message-id|agent> <message>",
		"/agent-room inbox",
		"/agent-room send <from> <to|all|human> <message>",
		"/agent-room compact <agent|all>",
		"/agent-room stop",
		"/agent-room destroy [run-id] [--force]",
	].join("\n");
}

function parseCreateArgs(args: string[]): { text: string; options: CreateRoomOptions } {
	const textParts: string[] = [];
	const options: CreateRoomOptions = {};
	for (let i = 0; i < args.length; i += 1) {
		const arg = args[i];
		if (arg === "--in-place" || arg === "--no-worktree") {
			options.useWorktree = false;
			continue;
		}
		if (arg === "--base") {
			options.baseRef = args[i + 1];
			i += 1;
			continue;
		}
		textParts.push(arg);
	}
	return { text: textParts.join(" ").trim(), options };
}

async function handleAgentRoomCommand(pi: ExtensionAPI, args: string, ctx: ExtensionCommandContext): Promise<void> {
	const [command = "status", ...rest] = splitCommand(args);

	if (command === "help") {
		ctx.ui.notify(usage(), "info");
		return;
	}

	if (command === "start") {
		const { text, options } = parseCreateArgs(rest);
		const name = text || "agent-room";
		const room = await createRoom(pi, ctx, name, options);
		await activateRoom(pi, ctx, room);
		ctx.ui.notify(`AgentRoom started: ${room.id}\nworkspace: ${relativeToCwd(room.controllerCwd, room.cwd)}`, "info");
		return;
	}

	if (command === "prd") {
		const { text: prdRef, options } = parseCreateArgs(rest);
		if (!prdRef) {
			ctx.ui.notify("Usage: /agent-room prd <issue-or-url>", "error");
			return;
		}
		ctx.ui.notify(`Loading PRD ${prdRef} and ready slices...`, "info");
		const { repo, prd, plan } = await loadPrdContext(ctx.cwd, prdRef);
		const roomOptions = await preparePrdBaseRef(ctx.cwd, { ...options, prd: prdMetadata(repo, prd, plan) });
		const room = await createRoom(pi, ctx, `prd-${prd.number}`, roomOptions);
		await activateRoom(pi, ctx, room);
		await promptAgent(room, "architect", buildPrdArchitectPrompt(repo, prd, plan));
		await promptAgent(room, "reviewer", buildPrdReviewerPrompt(repo, prd, plan));
		await promptAgent(room, "implementer", buildPrdImplementerPrompt(repo, prd, plan));
		ctx.ui.notify(
			`AgentRoom PRD run started: ${room.id}\nworkspace: ${relativeToCwd(room.controllerCwd, room.cwd)}\nslices: ${plan.ordered.map((slice) => `#${slice.number}`).join(" → ")}`,
			"info",
		);
		return;
	}

	if (command === "resume") {
		const runId = rest[0];
		if (!runId) {
			ctx.ui.notify("Usage: /agent-room resume <run-id>", "error");
			return;
		}
		const room = await loadRoom(pi, ctx, runId);
		await activateRoom(pi, ctx, room);
		ctx.ui.notify(`AgentRoom resumed: ${room.id}`, "info");
		for (const agentName of room.agents.keys()) void deliverInbox(room, agentName);
		return;
	}

	if (command === "unblock") {
		const runId = rest[0];
		const room = runId ? await loadRoom(pi, ctx, runId) : requireRoom();
		if (runId && room !== activeRoom) await activateRoom(pi, ctx, room);
		const workflow = prdWorkflow(room);
		if (!workflow) {
			ctx.ui.notify("Active run has no PRD workflow to unblock.", "error");
			return;
		}
		if (workflow.phase !== "blocked") {
			ctx.ui.notify(`PRD workflow is not blocked (phase: ${workflow.phase}).`, "info");
			return;
		}
		const priorReason = workflow.blockedReason ?? "unknown";
		if (isFinalArchitectureBlockedReason(priorReason)) {
			const finalReview = room.manifest.finalArchitectureReview;
			const fallbackFindings = priorReason.replace(/^Final architecture review requested changes:\s*/i, "");
			await requestFinalArchitectureFixSlice(room, pi, finalReview?.findings ?? fallbackFindings, finalReview?.verification, "agent-room");
			ctx.ui.notify(`AgentRoom unblocked: ${room.id} (phase: ${workflow.phase}).`, "info");
			return;
		}
		const slice = currentPrdSlice(room);
		// Re-enter at the last safe checkpoint. A current slice means commit/compact/assign
		// can be re-driven idempotently via "approved"; otherwise re-request final review.
		if (slice) {
			setWorkflowPhase(room, "approved");
			await saveManifest(room);
			await routeMessage(
				room,
				"agent-room",
				HUMAN_NAME,
				`Unblocked PRD workflow; re-driving slice ${prdSliceLabel(slice)}. Prior reason: ${oneLine(priorReason)}`,
				"unblock",
				pi,
			);
			await runPrdWorkflowAutomation(room, pi);
		} else {
			setWorkflowPhase(room, "final-reviewing");
			await saveManifest(room);
			await routeMessage(room, "agent-room", HUMAN_NAME, `Unblocked PRD workflow; re-requesting final architecture review. Prior reason: ${oneLine(priorReason)}`, "unblock", pi);
			await promptAgent(room, "architect", buildPrdFinalArchitectPrompt(room), true);
		}
		ctx.ui.notify(`AgentRoom unblocked: ${room.id} (phase: ${workflow.phase}).`, "info");
		return;
	}

	if (command === "list") {
		const rooms = await listRooms(ctx.cwd);
		const text = rooms.length
			? rooms
					.map((room) => {
						const workspace = relativeToCwd(ctx.cwd, room.workspaceCwd ?? room.cwd);
						const branch = room.worktree ? ` ${room.worktree.branch}` : " in-place";
						return `${room.id}  ${room.name}${branch}  ${workspace}  updated ${room.updatedAt}`;
					})
					.join("\n")
			: "No AgentRoom runs.";
		ctx.ui.notify(text, "info");
		return;
	}

	if (command === "status") {
		if (!activeRoom) {
			ctx.ui.notify("No active AgentRoom. Run /agent-room start.", "info");
			return;
		}
		updateDashboard(activeRoom, ctx);
		ctx.ui.notify(statusText(activeRoom), "info");
		return;
	}

	if (command === "ask") {
		const [target, ...messageParts] = rest;
		const message = messageParts.join(" ").trim();
		if (!target || !message) {
			ctx.ui.notify("Usage: /agent-room ask <agent|all> <message>", "error");
			return;
		}
		const room = requireRoom();
		if (target === "all") {
			for (const agentName of room.agents.keys()) await promptAgent(room, agentName, message);
		} else {
			await promptAgent(room, target, message);
		}
		ctx.ui.notify(`Queued ask for ${target}.`, "info");
		return;
	}

	if (command === "inbox") {
		const room = requireRoom();
		const messages = humanMessages(room).slice(-20);
		const text = messages.length
			? messages
					.map((message) => `${shortMessageId(message.id)}  ${message.createdAt}  ${message.from}  ${message.kind}\n${message.body}`)
					.join("\n\n---\n\n")
			: "Human inbox empty.";
		ctx.ui.notify(text, "info");
		return;
	}

	if (command === "reply" || command === "answer") {
		const [targetOrMessageId, ...messageParts] = rest;
		const message = messageParts.join(" ").trim();
		if (!targetOrMessageId || !message) {
			ctx.ui.notify("Usage: /agent-room reply <message-id|agent> <message>", "error");
			return;
		}
		const room = requireRoom();
		let target = room.agents.has(targetOrMessageId) ? targetOrMessageId : undefined;
		let body = message;
		let replyToId: string | undefined;
		if (!target) {
			const original = findMessageByIdPrefix(room, targetOrMessageId);
			if (!original || original.to !== HUMAN_NAME) {
				ctx.ui.notify(`No human-directed message found for ${targetOrMessageId}. Use /agent-room inbox.`, "error");
				return;
			}
			target = original.from;
			replyToId = original.id;
			body = `Reply to ${shortMessageId(original.id)} (${original.kind}):\n${message}`;
		}
		const result = await routeMessage(room, HUMAN_NAME, target, body, "human-reply", pi, replyToId);
		ctx.ui.notify(result, "info");
		return;
	}

	if (command === "send") {
		const [from, to, ...messageParts] = rest;
		const message = messageParts.join(" ").trim();
		if (!from || !to || !message) {
			ctx.ui.notify("Usage: /agent-room send <from> <to|all|human> <message>", "error");
			return;
		}
		const room = requireRoom();
		const results: string[] = [];
		if (to === "all") {
			for (const target of room.agents.keys()) {
				if (target !== from) results.push(await routeMessage(room, from, target, message, "human-relay", pi));
			}
		} else {
			results.push(await routeMessage(room, from, to, message, "human-relay", pi));
		}
		ctx.ui.notify(results.join("\n") || `No recipients for ${to}.`, "info");
		return;
	}

	if (command === "compact") {
		const target = rest[0];
		if (!target) {
			ctx.ui.notify("Usage: /agent-room compact <agent|all>", "error");
			return;
		}
		const room = requireRoom();
		const agents = (target === "all" ? [...room.agents.values()] : [room.agents.get(target)].filter(Boolean)) as ResidentAgent[];
		if (agents.length === 0) {
			ctx.ui.notify(`Unknown agent: ${target}`, "error");
			return;
		}
		for (const agent of agents) {
			void agent.session.compact("Preserve AgentRoom decisions, sent/received messages, current task state, file findings, and unresolved blockers.");
		}
		ctx.ui.notify(`Compaction queued for ${target}.`, "info");
		return;
	}

	if (command === "stop") {
		await disposeRoom(activeRoom);
		activeRoom = undefined;
		activeRunId = undefined;
		persistActiveRun(pi, undefined);
		clearDashboard(ctx);
		ctx.ui.notify("AgentRoom stopped.", "info");
		return;
	}

	if (command === "destroy") {
		await destroyRoom(pi, ctx, rest);
		return;
	}

	ctx.ui.notify(usage(), "error");
}

function statusText(room: AgentRoom): string {
	const rows = [...room.agents.values()].map((agent) => {
		const stats = agent.stats;
		const sessionFile = agent.session.sessionFile ? relativeToCwd(room.controllerCwd, agent.session.sessionFile) : "in-memory";
		return `${agent.role.name}: ${stats.status}, inbox ${stats.inbox}, turns ${stats.turns}, ${sessionFile}`;
	});
	const latest = latestHumanMessage(room);
	const workflow = prdWorkflow(room);
	return [
		`AgentRoom ${room.name} (${room.id})`,
		...(room.manifest.prd
			? [
					`prd: #${room.manifest.prd.number} ${room.manifest.prd.title}`,
					`slices: ${room.manifest.prd.orderedSlices.map(prdSlicePromptLabel).join(" -> ")}`,
				]
			: []),
		`state: ${relativeToCwd(room.controllerCwd, room.runDir)}`,
		`workspace: ${relativeToCwd(room.controllerCwd, room.cwd)}`,
		...(room.manifest.worktree ? [`branch: ${room.manifest.worktree.branch}`, `base: ${room.manifest.worktree.baseRef}`] : []),
		...(workflow ? [`workflow: ${workflow.phase}, current: ${currentPrdSliceLabel(room)}, queue: ${room.promptQueue.length}`] : []),
		...(room.manifest.pullRequest ? [`pr: #${room.manifest.pullRequest.number} ${room.manifest.pullRequest.url}`] : []),
		...(latest ? [`latest human message: ${shortMessageId(latest.id)} from ${latest.from} (${latest.kind})`] : []),
		...rows,
	].join("\n");
}

export default function agentRoomExtension(pi: ExtensionAPI) {
	pi.registerMessageRenderer(HUMAN_MESSAGE_TYPE, (message, _options, theme) => {
		const details = message.details as
			| { roomName?: string; messageId?: string; from?: string; kind?: string; createdAt?: string; replyHint?: string }
			| undefined;
		const kind = details?.kind ?? "message";
		const color = kind === "question" ? "warning" : kind.includes("blocker") || kind.includes("error") ? "error" : "accent";
		const id = details?.messageId ? shortMessageId(details.messageId) : "????????";
		let text = theme.fg(color, `${theme.bold("AgentRoom")} ${details?.roomName ?? ""} ${details?.from ?? "agent"} → human [${kind}] ${id}`);
		text += `\n${String(message.content)}`;
		if (details?.replyHint) text += `\n${theme.fg("dim", `reply: ${details.replyHint}`)}`;
		return new Text(text, 0, 0);
	});

	pi.on("session_start", async (_event, ctx) => {
		activeRunId = restoreActiveRun(ctx);
		if (activeRunId) {
			try {
				const room = await loadRoom(pi, ctx, activeRunId);
				await activateRoom(pi, ctx, room);
				for (const agentName of room.agents.keys()) void deliverInbox(room, agentName);
			} catch (error) {
				ctx.ui.notify(`AgentRoom restore failed: ${error instanceof Error ? error.message : String(error)}`, "error");
			}
		}
	});

	pi.on("session_shutdown", async () => {
		await disposeRoom(activeRoom);
	});

	pi.registerCommand("agent-room", {
		description: "Persistent resident sub-agents with mailbox communication and TUI tiles",
		getArgumentCompletions: (prefix: string) => {
			const commands = ["start", "prd", "resume", "unblock", "list", "status", "ask", "reply", "answer", "inbox", "send", "compact", "stop", "destroy", "help"];
			const agents = activeRoom ? [...activeRoom.agents.keys(), HUMAN_NAME, "all"] : [];
			return [...commands, ...agents]
				.filter((item) => item.startsWith(prefix))
				.map((item) => ({ value: item, label: item }));
		},
		handler: async (args, ctx) => {
			try {
				await handleAgentRoomCommand(pi, args, ctx);
			} catch (error) {
				ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
			}
		},
	});

	pi.registerCommand("room", {
		description: "Alias for /agent-room",
		handler: async (args, ctx) => {
			try {
				await handleAgentRoomCommand(pi, args, ctx);
			} catch (error) {
				ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
			}
		},
	});
}
