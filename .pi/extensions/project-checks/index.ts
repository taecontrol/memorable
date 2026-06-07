import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { createLintTool } from "./tools/lint.ts";
import { createRunTestsTool } from "./tools/run-tests.ts";

export default function (pi: ExtensionAPI) {
	pi.registerTool(createRunTestsTool(pi));
	pi.registerTool(createLintTool(pi));
}
