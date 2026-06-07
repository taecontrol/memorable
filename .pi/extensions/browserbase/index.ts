import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	formatSize,
	truncateHead,
	type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";

const API_BASE_URL = "https://api.browserbase.com/v1";
const ENV_KEY = "BROWSERBASE_API_KEY";

type SearchResponse = {
	query: string;
	requestId: string;
	results: Array<{
		id: string;
		title: string;
		url: string;
		author?: string;
		favicon?: string;
		image?: string;
		publishedDate?: string;
	}>;
};

type FetchResponse = {
	id?: string;
	statusCode: number;
	headers: Record<string, string>;
	content: string | Record<string, unknown>;
	contentType: string;
	encoding: string;
};

function browserbaseApiKey(): string {
	const apiKey = process.env[ENV_KEY]?.trim();
	if (apiKey) return apiKey;

	throw new Error(`Missing ${ENV_KEY}. Add ${ENV_KEY}=... to .pi/.env or export it before starting pi.`);
}

function errorMessageFromBody(body: unknown): string {
	if (!body || typeof body !== "object") return String(body ?? "No response body");

	const record = body as Record<string, unknown>;
	const message = record.message ?? record.error ?? record.detail;
	if (typeof message === "string") return message;

	return JSON.stringify(body);
}

async function postBrowserbase<T>(
	endpoint: "/search" | "/fetch",
	body: Record<string, unknown>,
	apiKey: string,
	signal?: AbortSignal,
): Promise<T> {
	const response = await fetch(`${API_BASE_URL}${endpoint}`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"x-bb-api-key": apiKey,
		},
		body: JSON.stringify(body),
		signal,
	});

	const rawText = await response.text();
	let parsed: unknown = rawText;
	if (rawText) {
		try {
			parsed = JSON.parse(rawText);
		} catch {
			parsed = rawText;
		}
	}

	if (!response.ok) {
		throw new Error(`Browserbase ${endpoint} failed (${response.status} ${response.statusText}): ${errorMessageFromBody(parsed)}`);
	}

	return parsed as T;
}

function formatSearchResponse(response: SearchResponse): string {
	const lines = [`Request ID: ${response.requestId}`, `Query: ${response.query}`, `Results: ${response.results.length}`, ""];

	response.results.forEach((result, index) => {
		lines.push(`${index + 1}. ${result.title}`);
		lines.push(`   URL: ${result.url}`);
		if (result.author) lines.push(`   Author: ${result.author}`);
		if (result.publishedDate) lines.push(`   Published: ${result.publishedDate}`);
		if (result.image) lines.push(`   Image: ${result.image}`);
		if (result.favicon) lines.push(`   Favicon: ${result.favicon}`);
	});

	return lines.join("\n");
}

async function saveFullOutput(text: string): Promise<string> {
	const dir = path.join(tmpdir(), "pi-browserbase");
	await mkdir(dir, { recursive: true });

	const filePath = path.join(dir, `${Date.now()}-${randomUUID()}.txt`);
	await writeFile(filePath, text, "utf8");
	return filePath;
}

async function formatFetchResponse(response: FetchResponse, requestedUrl: string, format: "raw" | "markdown" | "json"): Promise<string> {
	const header = [
		`URL: ${requestedUrl}`,
		response.id ? `Request ID: ${response.id}` : undefined,
		`Status: ${response.statusCode}`,
		`Content-Type: ${response.contentType}`,
		`Encoding: ${response.encoding}`,
		`Format: ${format}`,
	]
		.filter(Boolean)
		.join("\n");

	const contentText = typeof response.content === "string" ? response.content : JSON.stringify(response.content, null, 2);

	if (response.encoding.toLowerCase() === "base64") {
		const filePath = await saveFullOutput(contentText);
		return `${header}\n\n[Binary/base64 content omitted. Full base64 output saved to: ${filePath}]`;
	}

	const truncation = truncateHead(contentText, {
		maxBytes: DEFAULT_MAX_BYTES,
		maxLines: DEFAULT_MAX_LINES,
	});

	let output = `${header}\n\n${truncation.content}`;
	if (truncation.truncated) {
		const filePath = await saveFullOutput(contentText);
		output += `\n\n[Output truncated: ${truncation.outputLines} of ${truncation.totalLines} lines`;
		output += ` (${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}).`;
		output += ` Full output saved to: ${filePath}]`;
	}

	return output;
}

function removeUndefinedValues(input: Record<string, unknown>): Record<string, unknown> {
	return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "browserbase_search",
		label: "Browserbase Search",
		description: "Search the web using Browserbase Search. Returns up to 25 token-efficient search results.",
		promptSnippet: "Search the web with Browserbase Search for current public pages and URLs",
		promptGuidelines: [
			"Use browserbase_search when the user asks for current public web information or relevant URLs that are not available in the repo.",
			"Use browserbase_search before browserbase_fetch when you do not know the exact URL to fetch.",
		],
		parameters: Type.Object({
			query: Type.String({ description: "Search query, 1-200 characters.", minLength: 1, maxLength: 200 }),
			numResults: Type.Optional(
				Type.Integer({ description: "Number of search results to return, 1-25. Defaults to 10.", minimum: 1, maximum: 25 }),
			),
		}),
		async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
			const apiKey = browserbaseApiKey();
			const response = await postBrowserbase<SearchResponse>(
				"/search",
				removeUndefinedValues({ query: params.query, numResults: params.numResults }),
				apiKey,
				signal,
			);

			return {
				content: [{ type: "text", text: formatSearchResponse(response) }],
				details: {
					requestId: response.requestId,
					query: response.query,
					resultCount: response.results.length,
					results: response.results,
				},
			};
		},
	});

	pi.registerTool({
		name: "browserbase_fetch",
		label: "Browserbase Fetch",
		description:
			"Fetch a URL through Browserbase. Supports raw, markdown, or JSON extraction. Does not execute JavaScript. Output is truncated to 50KB/2000 lines when needed.",
		promptSnippet: "Fetch page content from a known URL with Browserbase Fetch",
		promptGuidelines: [
			"Use browserbase_fetch for a known URL; prefer format=\"markdown\" for LLM-readable web pages.",
			"browserbase_fetch does not execute JavaScript. If content is missing because the page needs JavaScript, say that and consider a browser session instead.",
			"Only pass schema to browserbase_fetch when format=\"json\".",
		],
		parameters: Type.Object({
			url: Type.String({ description: "Absolute URL to fetch, including http:// or https://." }),
			format: Type.Optional(
				StringEnum(["raw", "markdown", "json"] as const, {
					description: "Output format. Defaults to raw. Use markdown for readable pages; use json with schema for structured extraction.",
				}),
			),
			allowRedirects: Type.Optional(Type.Boolean({ description: "Follow HTTP redirects. Defaults to false." })),
			allowInsecureSsl: Type.Optional(
				Type.Boolean({ description: "Bypass TLS certificate verification. Use only for trusted targets. Defaults to false." }),
			),
			proxies: Type.Optional(Type.Boolean({ description: "Route through Browserbase's proxy network. Defaults to false." })),
			schema: Type.Optional(
				Type.Object(
					{},
					{
						description: "JSON Schema object for structured extraction. Only valid when format is json.",
						additionalProperties: true,
					},
				),
			),
		}),
		async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
			if (params.schema !== undefined && params.format !== "json") {
				throw new Error('browserbase_fetch parameter "schema" is only valid when format is "json".');
			}

			const format = params.format ?? "raw";
			const apiKey = browserbaseApiKey();
			const response = await postBrowserbase<FetchResponse>(
				"/fetch",
				removeUndefinedValues({
					url: params.url,
					format: params.format,
					allowRedirects: params.allowRedirects,
					allowInsecureSsl: params.allowInsecureSsl,
					proxies: params.proxies,
					schema: params.schema,
				}),
				apiKey,
				signal,
			);

			return {
				content: [{ type: "text", text: await formatFetchResponse(response, params.url, format) }],
				details: {
					requestId: response.id,
					url: params.url,
					statusCode: response.statusCode,
					contentType: response.contentType,
					encoding: response.encoding,
					headers: response.headers,
					format,
				},
			};
		},
	});
}
