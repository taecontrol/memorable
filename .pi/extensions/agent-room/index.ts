import { execFile as execFileCallback } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

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
import { Type } from "typebox";

const STATE_TYPE = "agent-room-state";
const WIDGET_KEY = "agent-room";
const RUNS_DIR = [".pi", "agent-room", "runs"];
const WORKTREES_DIR = [".pi", "agent-room", "worktrees"];
const MAX_TILE_MESSAGE = 72;
const DEFAULT_TOOLS = ["read", "bash", "edit", "write", "grep", "find", "ls"];
const READ_ONLY_TOOLS = ["read", "bash", "grep", "find", "ls"];
const execFile = promisify(execFileCallback);

type AgentStatus = "idle" | "running" | "queued" | "blocked" | "error";

type RoomStateEntry = {
	type: string;
	customType?: string;
	data?: { activeRunId?: string | null };
};

type AgentRole = {
	name: string;
	title: string;
	description: string;
	tools: string[];
	systemPrompt: string;
};

type AgentManifest = {
	name: string;
	title: string;
	description: string;
	sessionFile: string;
	deliveredMessageIds: string[];
};

type WorktreeInfo = {
	path: string;
	branch: string;
	baseRef: string;
	createdAt: string;
};

type RoomManifest = {
	id: string;
	name: string;
	/** Agent workspace cwd. Kept as cwd for older manifests and status readability. */
	cwd: string;
	controllerCwd?: string;
	workspaceCwd?: string;
	worktree?: WorktreeInfo;
	createdAt: string;
	updatedAt: string;
	agents: AgentManifest[];
};

type RoomMessage = {
	id: string;
	createdAt: string;
	from: string;
	to: string;
	kind: string;
	body: string;
};

type AgentStats = {
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

type ResidentAgent = {
	role: AgentRole;
	manifest: AgentManifest;
	session: AgentSession;
	unsubscribe?: () => void;
	stats: AgentStats;
};

type AgentRoom = {
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
	lastCtx?: ExtensionContext;
	stopped: boolean;
};

const DEFAULT_ROLES: AgentRole[] = [
	{
		name: "implementer",
		title: "Implementer",
		description: "Persistent coding agent. Owns file mutations and implementation memory.",
		tools: DEFAULT_TOOLS,
		systemPrompt: `You are the persistent Implementer in an AgentRoom.

You keep context across turns. Own implementation work. You may edit files, run tests, and use bash.

Communication rules:
- Use agent_send to ask the reviewer for reviews or clarification.
- Use agent_broadcast for important implementation summaries.
- Keep messages short but include exact files changed, commands run, and blockers.
- Do not assume other agents saw your terminal output unless you send it.
- Prefer vertical tracer-bullet work and narrow tests.
- Never commit unless explicitly instructed by the human/coordinator.`,
	},
	{
		name: "reviewer",
		title: "Reviewer",
		description: "Persistent code reviewer. Remembers prior findings and review context.",
		tools: READ_ONLY_TOOLS,
		systemPrompt: `You are the persistent Reviewer in an AgentRoom.

You keep context across turns. Review implementation work and send actionable findings back to implementer.

Hard rules:
- Review only. Do not edit files.
- Bash is read-only: git diff, git status, grep, find, test commands are allowed; no mutation commands.
- Use agent_send to return findings to implementer.
- Classify findings as blocking or non-blocking.
- Include exact file paths and line references when possible.`,
	},
	{
		name: "architect",
		title: "Architect",
		description: "Persistent architecture reviewer. Tracks cross-slice/product risks.",
		tools: READ_ONLY_TOOLS,
		systemPrompt: `You are the persistent Architect in an AgentRoom.

You keep context across turns. Focus on architecture, domain language, temporal semantics, boundaries, and maintainability.

Hard rules:
- Review only. Do not edit files.
- Use agent_broadcast for architecture decisions or risks relevant to all agents.
- Use agent_send for targeted blockers.
- Be concise, specific, and grounded in files/docs.`,
	},
];

let activeRoom: AgentRoom | undefined;
let activeRunId: string | undefined;

function oneLine(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

function truncate(value: string, max = MAX_TILE_MESSAGE): string {
	const text = oneLine(value);
	if (text.length <= max) return text;
	return `${text.slice(0, Math.max(0, max - 1))}…`;
}

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

async function git(cwd: string, args: string[]): Promise<{ stdout: string; stderr: string }> {
	const result = await execFile("git", args, { cwd, maxBuffer: 10 * 1024 * 1024 });
	return { stdout: String(result.stdout), stderr: String(result.stderr) };
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

function nowIso(): string {
	return new Date().toISOString();
}

function runsRoot(cwd: string): string {
	return path.join(cwd, ...RUNS_DIR);
}

function runDir(cwd: string, runId: string): string {
	return path.join(runsRoot(cwd), runId);
}

function manifestPath(runDirPath: string): string {
	return path.join(runDirPath, "manifest.json");
}

function mailboxPath(runDirPath: string): string {
	return path.join(runDirPath, "mailbox.jsonl");
}

async function ensureDir(dir: string): Promise<void> {
	await fs.mkdir(dir, { recursive: true });
}

async function readJson<T>(filePath: string): Promise<T | undefined> {
	try {
		return JSON.parse(await fs.readFile(filePath, "utf8")) as T;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
		throw error;
	}
}

async function writeJson(filePath: string, value: unknown): Promise<void> {
	await ensureDir(path.dirname(filePath));
	await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function appendJsonl(filePath: string, value: unknown): Promise<void> {
	await ensureDir(path.dirname(filePath));
	await fs.appendFile(filePath, `${JSON.stringify(value)}\n`, "utf8");
}

async function readMailbox(filePath: string): Promise<RoomMessage[]> {
	try {
		const content = await fs.readFile(filePath, "utf8");
		return content
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter(Boolean)
			.map((line) => JSON.parse(line) as RoomMessage);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
		throw error;
	}
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

function roleByName(name: string): AgentRole | undefined {
	return DEFAULT_ROLES.find((role) => role.name === name);
}

function allRoleNames(): string[] {
	return DEFAULT_ROLES.map((role) => role.name);
}

function agentSystemPrompt(room: AgentRoom, role: AgentRole): string {
	return `${role.systemPrompt}

# AgentRoom

Room: ${room.name} (${room.id})
Your agent name: ${role.name}
Peers: ${allRoleNames().filter((name) => name !== role.name).join(", ")}
Working directory: ${room.cwd}
${room.manifest.worktree ? `Git worktree branch: ${room.manifest.worktree.branch}\nGit worktree path: ${room.manifest.worktree.path}` : "Workspace mode: current working tree"}

You are resident: your Pi session persists under ${relativeToCwd(room.controllerCwd, room.runDir)} and future prompts preserve your context.

Available communication tools:
- agent_send: send a direct message to another resident agent.
- agent_broadcast: send a message to all other resident agents.
- agent_inbox: inspect recent messages addressed to you.
- agent_room_status: inspect peer status.

When sending another agent work, include enough context for them to act without reading your mind.`;
}

function buildCommunicationTools(room: AgentRoom, agentName: string): ToolDefinition[] {
	return [
		defineTool({
			name: "agent_send",
			label: "Agent Send",
			description: "Send a message to another persistent AgentRoom agent.",
			parameters: Type.Object({
				to: Type.String({ description: "Target agent name" }),
				message: Type.String({ description: "Message body" }),
				kind: Type.Optional(Type.String({ description: "Message kind, e.g. review-request, finding, blocker, note" })),
			}),
			async execute(_toolCallId, params) {
				const result = await routeMessage(room, agentName, params.to, params.message, params.kind ?? "message");
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
					await routeMessage(room, agentName, target, params.message, params.kind ?? "broadcast");
				}
				return { content: [{ type: "text", text: `Broadcast sent to ${targets.join(", ") || "nobody"}.` }], details: { targets } };
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
				const text = messages.length
					? messages.map(formatMailboxMessage).join("\n\n")
					: "Inbox empty.";
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
				return { content: [{ type: "text", text: rows.join("\n") }], details: { room: room.id } };
			},
		}),
	];
}

function formatMailboxMessage(message: RoomMessage): string {
	return `From: ${message.from}\nKind: ${message.kind}\nAt: ${message.createdAt}\n\n${message.body}`;
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
		tools: [...role.tools, "agent_send", "agent_broadcast", "agent_inbox", "agent_room_status"],
		customTools: buildCommunicationTools(room, role.name),
	});

	const stats = statsFromSession(session);
	const resident: ResidentAgent = { role, manifest, session, stats };
	resident.unsubscribe = session.subscribe((event) => handleAgentEvent(room, resident, event));
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

function handleAgentEvent(room: AgentRoom, agent: ResidentAgent, event: AgentSessionEvent): void {
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
	}

	if (event.type === "message_update" && event.message?.role === "assistant") {
		const text = event.message.content.find((part) => part.type === "text")?.text;
		if (text) stats.lastMessage = truncate(text);
	}

	if (event.type === "agent_end") {
		const fresh = statsFromSession(agent.session);
		agent.stats = { ...fresh, inbox: pendingMessagesFor(room, agent.role.name).length };
		updateDashboard(room);
		void deliverInbox(room, agent.role.name);
		void saveManifest(room);
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

function pendingMessagesFor(room: AgentRoom, agentName: string): RoomMessage[] {
	const agent = room.agents.get(agentName);
	if (!agent) return [];
	const delivered = new Set(agent.manifest.deliveredMessageIds);
	return room.messages.filter((message) => message.to === agentName && !delivered.has(message.id));
}

async function routeMessage(room: AgentRoom, from: string, to: string, body: string, kind = "message"): Promise<string> {
	const target = room.agents.get(to);
	if (!target) {
		return `Unknown agent "${to}". Available: ${[...room.agents.keys()].join(", ")}`;
	}

	const message: RoomMessage = {
		id: randomUUID(),
		createdAt: nowIso(),
		from,
		to,
		kind,
		body,
	};
	room.messages.push(message);
	await appendJsonl(room.mailboxPath, message);
	target.stats.inbox = pendingMessagesFor(room, to).length;
	updateDashboard(room);
	void deliverInbox(room, to);
	return `Message sent to ${to}.`;
}

async function deliverInbox(room: AgentRoom, agentName: string): Promise<void> {
	if (room.stopped) return;
	const agent = room.agents.get(agentName);
	if (!agent) return;
	if (agent.session.isStreaming) {
		agent.stats.status = "queued";
		updateDashboard(room);
		return;
	}

	const pending = pendingMessagesFor(room, agentName);
	if (pending.length === 0) {
		agent.stats.inbox = 0;
		updateDashboard(room);
		return;
	}

	for (const message of pending) agent.manifest.deliveredMessageIds.push(message.id);
	agent.stats.inbox = 0;
	await saveManifest(room);
	await promptAgent(room, agentName, formatInboxPrompt(pending));
}

async function promptAgent(room: AgentRoom, agentName: string, prompt: string): Promise<void> {
	if (room.stopped) return;
	const agent = room.agents.get(agentName);
	if (!agent) throw new Error(`Unknown agent: ${agentName}`);

	agent.stats.currentTask = truncate(prompt, 80);
	if (agent.session.isStreaming) {
		agent.stats.status = "queued";
		updateDashboard(room);
		await agent.session.followUp(prompt);
		return;
	}

	updateDashboard(room);
	void agent.session
		.prompt(prompt, { source: "extension", expandPromptTemplates: false })
		.catch((error: unknown) => {
			agent.stats.status = "error";
			agent.stats.error = error instanceof Error ? error.message : String(error);
			agent.stats.lastMessage = agent.stats.error;
			updateDashboard(room);
		});
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

type CreateRoomOptions = {
	useWorktree?: boolean;
	baseRef?: string;
};

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
	const agents = [...room.agents.values()];
	if (agents.length === 0) return [];
	const gap = 2;
	const columns = Math.max(1, Math.min(3, Math.floor((width + gap) / 34), agents.length));
	const tileWidth = Math.max(28, Math.floor((width - gap * (columns - 1)) / columns));
	const rows: string[] = [];
	rows.push(theme.fg("accent", `AgentRoom ${room.name} (${room.id})`));

	for (let i = 0; i < agents.length; i += columns) {
		const group = agents.slice(i, i + columns).map((agent, index) => renderTile(agent, tileWidth, theme, i + index));
		const height = Math.max(...group.map((tile) => tile.length));
		for (let line = 0; line < height; line += 1) {
			rows.push(group.map((tile) => tile[line] ?? " ".repeat(tileWidth)).join(" ".repeat(gap)));
		}
	}
	return rows;
}

function renderTile(agent: ResidentAgent, width: number, theme: any, index: number): string[] {
	const stats = agent.stats;
	const color = ["borderAccent", "success", "error", "warning", "accent", "muted"][index % 6];
	const title = ` ${agent.role.title} `;
	const top = `┌${title}${"─".repeat(Math.max(0, width - title.length - 2))}┐`;
	const bottom = `└${"─".repeat(Math.max(0, width - 2))}┘`;
	const statusIcon = stats.status === "running" ? "●" : stats.status === "queued" ? "◌" : stats.status === "error" ? "✗" : "○";
	const status = `${statusIcon} ${stats.status}`;
	const usage = `${stats.turns} turns ↑${formatTokens(stats.input)} ↓${formatTokens(stats.output)} $${stats.cost.toFixed(4)}`;
	const body = [
		status,
		truncate(stats.currentTask ?? agent.role.description, width - 4),
		`inbox ${stats.inbox} ${usage}`,
		truncate(stats.error ?? stats.lastMessage ?? "-", width - 4),
	];
	return [theme.fg(color, top), ...body.map((line) => theme.fg(color, tileLine(line, width))), theme.fg(color, bottom)];
}

function tileLine(text: string, width: number): string {
	const innerWidth = Math.max(0, width - 4);
	const clipped = text.length > innerWidth ? `${text.slice(0, Math.max(0, innerWidth - 1))}…` : text;
	return `│ ${clipped.padEnd(innerWidth, " ")} │`;
}

function formatTokens(value: number): string {
	if (!Number.isFinite(value) || value <= 0) return "0";
	if (value < 1_000) return String(Math.round(value));
	if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
	return `${(value / 1_000_000).toFixed(1)}M`;
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
		"/agent-room list",
		"/agent-room status",
		"/agent-room ask <agent|all> <message>",
		"/agent-room send <from> <to|all> <message>",
		"/agent-room compact <agent|all>",
		"/agent-room stop",
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
		const room = await createRoom(pi, ctx, `prd-${safeId(prdRef)}`, options);
		await activateRoom(pi, ctx, room);
		await promptAgent(
			room,
			"implementer",
			`Prepare an implementation plan for PRD ${prdRef}. Fetch/read the issue if needed. Do not implement until you have enough context. Send reviewer and architect concise context via agent_send or agent_broadcast.`,
		);
		await promptAgent(
			room,
			"reviewer",
			`You are attached to PRD ${prdRef}. Wait for implementer messages. When asked, review diffs and send findings via agent_send.`,
		);
		await promptAgent(
			room,
			"architect",
			`You are attached to PRD ${prdRef}. Review product/domain/architecture risks. Broadcast blockers or constraints.`,
		);
		ctx.ui.notify(`AgentRoom PRD run started: ${room.id}\nworkspace: ${relativeToCwd(room.controllerCwd, room.cwd)}`, "info");		return;
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

	if (command === "send") {
		const [from, to, ...messageParts] = rest;
		const message = messageParts.join(" ").trim();
		if (!from || !to || !message) {
			ctx.ui.notify("Usage: /agent-room send <from> <to|all> <message>", "error");
			return;
		}
		const room = requireRoom();
		if (to === "all") {
			for (const target of room.agents.keys()) {
				if (target !== from) await routeMessage(room, from, target, message, "human-relay");
			}
		} else {
			await routeMessage(room, from, to, message, "human-relay");
		}
		ctx.ui.notify(`Sent ${from} -> ${to}.`, "info");
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

	ctx.ui.notify(usage(), "error");
}

function statusText(room: AgentRoom): string {
	const rows = [...room.agents.values()].map((agent) => {
		const stats = agent.stats;
		const sessionFile = agent.session.sessionFile ? relativeToCwd(room.controllerCwd, agent.session.sessionFile) : "in-memory";
		return `${agent.role.name}: ${stats.status}, inbox ${stats.inbox}, turns ${stats.turns}, ${sessionFile}`;
	});
	return [
		`AgentRoom ${room.name} (${room.id})`,
		`state: ${relativeToCwd(room.controllerCwd, room.runDir)}`,
		`workspace: ${relativeToCwd(room.controllerCwd, room.cwd)}`,
		...(room.manifest.worktree ? [`branch: ${room.manifest.worktree.branch}`] : []),
		...rows,
	].join("\n");
}

export default function agentRoomExtension(pi: ExtensionAPI) {
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
			const commands = ["start", "prd", "resume", "list", "status", "ask", "send", "compact", "stop", "help"];
			const agents = activeRoom ? [...activeRoom.agents.keys(), "all"] : [];
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
