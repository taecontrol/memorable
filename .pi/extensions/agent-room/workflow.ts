import type { AgentRoom, PrdRunMetadata, PrdSliceMetadata, PrdWorkflow, PrdWorkflowPhase } from "./types.ts";

/**
 * PRD workflow phase machine.
 *
 * This module is the single source of truth for the PRD run lifecycle. Every
 * phase write must go through `setWorkflowPhase`, which validates the move
 * against `PRD_TRANSITIONS` and keeps `blockedReason` consistent. The side
 * effects each phase drives (commit, compact, publish, prompts) live with the
 * room runtime; this file only owns *which phases are reachable from which*.
 *
 *   implementing ──submit / review-request──▶ reviewing
 *   reviewing ──changes_requested──▶ implementing
 *   reviewing ──approved──▶ approved
 *   approved ──automation──▶ committing ──▶ compacting
 *   compacting ──next slice──▶ implementing
 *   compacting ──all slices committed──▶ final-reviewing
 *   final-reviewing ──architect approved──▶ publishing ──PR opened──▶ done
 *   final-reviewing ──architect changes_requested──▶ implementing (fix slice)
 *   publishing ──publish fails──▶ blocked
 *   <any phase> ──unexpected error──▶ blocked
 *   blocked ──/agent-room unblock──▶ approved | implementing | final-reviewing
 *
 * `architecting` and `reviewer-setup` are reserved phases that current runs do
 * not enter (runs start at `implementing`); they are kept legal for forward
 * compatibility.
 */
const PRD_TRANSITIONS: Record<PrdWorkflowPhase, PrdWorkflowPhase[]> = {
	architecting: ["reviewer-setup", "implementing"],
	"reviewer-setup": ["implementing"],
	implementing: ["reviewing"],
	reviewing: ["implementing", "approved"],
	approved: ["committing"],
	committing: ["compacting"],
	compacting: ["implementing", "final-reviewing"],
	"final-reviewing": ["implementing", "publishing"],
	publishing: ["done"],
	// finish_architecture_review accepts a re-run while already `done`.
	done: ["implementing", "publishing"],
	blocked: ["approved", "implementing", "final-reviewing"],
};

/**
 * A phase move is legal when it is a no-op (same phase), a fail-loud drop to
 * `blocked` (always allowed), or an edge declared in `PRD_TRANSITIONS`.
 */
export function isLegalPrdTransition(from: PrdWorkflowPhase, to: PrdWorkflowPhase): boolean {
	if (from === to) return true;
	if (to === "blocked") return true;
	return PRD_TRANSITIONS[from]?.includes(to) ?? false;
}

export function prdWorkflow(room: AgentRoom): PrdWorkflow | undefined {
	return room.manifest.workflow?.kind === "prd" ? room.manifest.workflow : undefined;
}

export function currentPrdSlice(room: AgentRoom): PrdRunMetadata["orderedSlices"][number] | undefined {
	const workflow = prdWorkflow(room);
	return workflow ? room.manifest.prd?.orderedSlices[workflow.currentSliceIndex] : undefined;
}

export function prdSliceLabel(slice: PrdSliceMetadata): string {
	return slice.synthetic === "final-architecture-fix" ? slice.title : `#${slice.number} ${slice.title}`;
}

export function currentPrdSliceLabel(room: AgentRoom): string {
	const slice = currentPrdSlice(room);
	return slice ? prdSliceLabel(slice) : "none";
}

/**
 * The only place a PRD workflow phase is written. Throws on an illegal
 * transition so workflow bugs fail loudly instead of silently corrupting run
 * state. Entering `blocked` records the optional reason; leaving `blocked`
 * (or any non-blocked phase) clears any stale reason.
 */
export function setWorkflowPhase(room: AgentRoom, to: PrdWorkflowPhase, opts: { blockedReason?: string } = {}): void {
	const workflow = prdWorkflow(room);
	if (!workflow) throw new Error("No PRD workflow is active.");
	if (!isLegalPrdTransition(workflow.phase, to)) {
		throw new Error(`Illegal PRD workflow transition: ${workflow.phase} -> ${to}.`);
	}
	workflow.phase = to;
	if (to === "blocked") {
		if (opts.blockedReason) workflow.blockedReason = opts.blockedReason;
	} else {
		delete workflow.blockedReason;
	}
}
