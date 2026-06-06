import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

import type { ResidentAgent } from "./types.ts";

const MAX_TILE_MESSAGE = 72;

export function oneLine(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

export function fitLine(value: string, width: number, ellipsis = ""): string {
	const maxWidth = Math.max(0, Math.floor(width));
	if (maxWidth === 0) return "";
	if (visibleWidth(value) <= maxWidth) return value;
	return truncateToWidth(value, maxWidth, ellipsis);
}

export function padToWidth(value: string, width: number): string {
	const clipped = fitLine(value, width);
	return `${clipped}${" ".repeat(Math.max(0, Math.floor(width) - visibleWidth(clipped)))}`;
}

export function borderLine(left: string, title: string, right: string, width: number): string {
	const maxWidth = Math.max(0, Math.floor(width));
	if (maxWidth === 0) return "";
	if (maxWidth === 1) return left;
	const innerWidth = Math.max(0, maxWidth - 2);
	const clippedTitle = fitLine(title, innerWidth);
	return `${left}${clippedTitle}${"─".repeat(Math.max(0, innerWidth - visibleWidth(clippedTitle)))}${right}`;
}

export function truncate(value: string, max = MAX_TILE_MESSAGE): string {
	return fitLine(oneLine(value), max, "…");
}

export function renderTile(agent: ResidentAgent, width: number, theme: any, index: number): string[] {
	const tileWidth = Math.max(1, Math.floor(width));
	const stats = agent.stats;
	const color = ["borderAccent", "success", "error", "warning", "accent", "muted"][index % 6];
	const title = ` ${agent.role.title} `;
	const top = borderLine("┌", title, "┐", tileWidth);
	const bottom = borderLine("└", "", "┘", tileWidth);
	const statusIcon = stats.status === "running" ? "●" : stats.status === "queued" ? "◌" : stats.status === "error" ? "✗" : "○";
	const status = `${statusIcon} ${stats.status}`;
	const usage = `${stats.turns} turns ↑${formatTokens(stats.input)} ↓${formatTokens(stats.output)} $${stats.cost.toFixed(4)}`;
	const body = [
		status,
		stats.currentTask ?? agent.role.description,
		`inbox ${stats.inbox} ${usage}`,
		stats.error ?? stats.lastMessage ?? "-",
	];
	return [theme.fg(color, top), ...body.map((line) => theme.fg(color, tileLine(line, tileWidth))), theme.fg(color, bottom)].map((line) => fitLine(line, tileWidth));
}

export function tileLine(text: string, width: number): string {
	const maxWidth = Math.max(0, Math.floor(width));
	if (maxWidth === 0) return "";
	if (maxWidth === 1) return "│";
	if (maxWidth === 2) return "││";
	if (maxWidth === 3) return "│ │";
	const innerWidth = Math.max(0, maxWidth - 4);
	return `│ ${padToWidth(fitLine(oneLine(text), innerWidth, "…"), innerWidth)} │`;
}

export function formatTokens(value: number): string {
	if (!Number.isFinite(value) || value <= 0) return "0";
	if (value < 1_000) return String(Math.round(value));
	if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
	return `${(value / 1_000_000).toFixed(1)}M`;
}
