import type { AgentSession, ExtensionContext } from "@earendil-works/pi-coding-agent";

export type AgentStatus = "idle" | "running" | "queued" | "blocked" | "error";

export type IssueState = "OPEN" | "CLOSED" | string;

export type GhLabel = {
	name: string;
};

export type GhComment = {
	body?: string | null;
	author?: { login?: string | null } | null;
	createdAt?: string | null;
};

export type Issue = {
	number: number;
	title: string;
	body?: string | null;
	labels?: GhLabel[];
	state: IssueState;
	comments?: GhComment[];
	url?: string;
};

export type IssueRef = {
	repo: string;
	number: number;
};

export type SkippedSlice = {
	issue: Issue;
	reason: string;
};

export type SlicePlan = {
	ordered: Issue[];
	skipped: SkippedSlice[];
	blockersBySlice: Map<number, number[]>;
};

export type PrdRunMetadata = {
	repo: string;
	number: number;
	title: string;
	url?: string;
	context?: string;
	orderedSlices: Array<{ number: number; title: string; url?: string; blockers: number[] }>;
	skippedSlices: Array<{ number: number; title: string; url?: string; reason: string }>;
};

export type PrdWorkflowPhase =
	| "architecting"
	| "reviewer-setup"
	| "implementing"
	| "reviewing"
	| "approved"
	| "committing"
	| "compacting"
	| "final-reviewing"
	| "publishing"
	| "done"
	| "blocked";

export type PrdWorkflow = {
	kind: "prd";
	currentSliceIndex: number;
	phase: PrdWorkflowPhase;
	approvedSlices: number[];
	committedSlices: number[];
	blockedReason?: string;
};

export type AgentPromptRequest = {
	id: string;
	agentName: string;
	prompt: string;
	deliveredMessageIds: string[];
};

export type RoomStateEntry = {
	type: string;
	customType?: string;
	data?: { activeRunId?: string | null };
};

export type AgentRole = {
	name: string;
	title: string;
	description: string;
	tools: string[];
	systemPrompt: string;
};

export type AgentManifest = {
	name: string;
	title: string;
	description: string;
	sessionFile: string;
	deliveredMessageIds: string[];
};

export type WorktreeInfo = {
	path: string;
	branch: string;
	baseRef: string;
	createdAt: string;
};

export type PullRequestMetadata = {
	number: number;
	url: string;
	title: string;
	createdAt: string;
};

export type FinalArchitectureReviewMetadata = {
	status: "approved" | "changes_requested";
	findings: string;
	verification?: string;
	reviewedAt: string;
};

export type RoomManifest = {
	id: string;
	name: string;
	/** Agent workspace cwd. Kept as cwd for older manifests and status readability. */
	cwd: string;
	controllerCwd?: string;
	workspaceCwd?: string;
	worktree?: WorktreeInfo;
	prd?: PrdRunMetadata;
	workflow?: PrdWorkflow;
	pullRequest?: PullRequestMetadata;
	finalArchitectureReview?: FinalArchitectureReviewMetadata;
	createdAt: string;
	updatedAt: string;
	agents: AgentManifest[];
};

export type RoomMessage = {
	id: string;
	createdAt: string;
	from: string;
	to: string;
	kind: string;
	body: string;
	replyToId?: string;
};

export type AgentStats = {
	status: AgentStatus;
	currentTask?: string;
	lastMessage?: string;
	turns: number;
	input: number;
	output: number;
	cost: number;
	inbox: number;
	error?: string;
};

export type ResidentAgent = {
	role: AgentRole;
	manifest: AgentManifest;
	session: AgentSession;
	unsubscribe?: () => void;
	stats: AgentStats;
};

export type AgentRoom = {
	id: string;
	name: string;
	/** Agent workspace cwd. */
	cwd: string;
	/** Pi session cwd that owns AgentRoom runtime state. */
	controllerCwd: string;
	runDir: string;
	mailboxPath: string;
	manifestPath: string;
	manifest: RoomManifest;
	messages: RoomMessage[];
	agents: Map<string, ResidentAgent>;
	promptQueue: AgentPromptRequest[];
	queuedMessageIds: Set<string>;
	activeAgentName?: string;
	automationActive: boolean;
	lastCtx?: ExtensionContext;
	stopped: boolean;
};

export type GhPullRequest = {
	number: number;
	url: string;
	title: string;
	isDraft: boolean;
};

export type CreateRoomOptions = {
	useWorktree?: boolean;
	baseRef?: string;
	prd?: PrdRunMetadata;
};
