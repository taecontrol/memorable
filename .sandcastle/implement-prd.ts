import {
  createSandbox,
  opencode,
  type AgentStreamEvent,
  type LoggingOption,
  type Sandbox,
  type SandboxRunResult,
} from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { Buffer } from "node:buffer";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { access, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const MODEL = "openai/gpt-5.5";
const IMPLEMENTER_VARIANT = "high";
const REVIEWER_VARIANT = "xhigh";
const IMAGE_NAME = "memorable-sandcastle-opencode:latest";
const COMPLETION_SIGNAL = "<promise>COMPLETE</promise>";
const MAX_SLICE_ATTEMPTS = 5;
const NEO4J_USER = "neo4j";
const NEO4J_PASSWORD = "memorable";
const AGENT_PROGRESS_INSTRUCTIONS = `- Print a short progress line before each major phase, before running tests, and after test results.
- Start progress lines with "progress:".
- Keep each progress line under 160 characters and never print secrets or full command output.`;

type IssueState = "OPEN" | "CLOSED" | string;

type GhLabel = {
  name: string;
};

type GhComment = {
  body?: string | null;
};

type Issue = {
  number: number;
  title: string;
  body?: string | null;
  labels?: GhLabel[];
  state: IssueState;
  comments?: GhComment[];
  url?: string;
};

type SkippedSlice = {
  issue: Issue;
  reason: string;
};

type SlicePlan = {
  ordered: Issue[];
  skipped: SkippedSlice[];
  blockersBySlice: Map<number, number[]>;
};

type ReviewStatus =
  | "clean"
  | "non_blocking_findings"
  | "blocking_findings"
  | "blocked_on_upstream";

type ReviewFinding = {
  severity: string;
  file?: string | null;
  line?: number | null;
  fix: string;
};

type ReviewResult = {
  status: ReviewStatus;
  findings: ReviewFinding[];
};

type CompletedSlice = {
  issue: Issue;
  commitSha: string;
  review: ReviewResult;
};

type EscalatedReason = "needs-human" | "blocked-by-upstream-failure";

type EscalatedSlice = {
  issue: Issue;
  reason: EscalatedReason;
  detail: string;
  findings: ReviewFinding[];
  attempts: number;
};

type PriorAttempt = {
  attempt: number;
  status: ReviewStatus;
  findings: ReviewFinding[];
  direction: string;
};

type SliceState = {
  status: "done" | "needs-human" | "blocked-upstream" | "pending";
  commitSha?: string;
  attempts: number;
  lastFindings?: ReviewFinding[];
  reason?: string;
};

type RunState = {
  prd: number;
  branch: string;
  updatedAt: string;
  slices: Record<number, SliceState>;
};

type SliceOutcome =
  | { kind: "completed"; completed: CompletedSlice }
  | { kind: "escalated"; escalated: EscalatedSlice };

type CommandResult = {
  command: string;
  stdout: string;
  stderr: string;
  exitCode: number;
};

type CommandOptions = {
  cwd?: string;
  env?: Record<string, string>;
  input?: string;
  allowFailure?: boolean;
  stream?: boolean;
};

type CheckResult = {
  command: string;
  exitCode: number;
  stdout: string;
  stderr: string;
};

type VerificationSummary = {
  passed: boolean;
  checks: CheckResult[];
};

type Neo4jRuntime = {
  containerName: string;
  networkName: string;
  hostHttpPort: string;
  hostBoltPort: string;
};

type LockHandle = {
  path: string;
};

type PullRequest = {
  number: number;
  url: string;
  title: string;
  body?: string | null;
  isDraft: boolean;
};

class CommandFailed extends Error {
  readonly result: CommandResult;

  constructor(result: CommandResult) {
    super(
      `Command failed (${result.exitCode}): ${result.command}\n${tail(
        result.stderr || result.stdout,
        4000,
      )}`,
    );
    this.result = result;
  }
}

async function main() {
  const input = process.argv[2];
  if (!input) {
    throw new Error("Usage: pnpm implement-prd <prd-issue-url-or-number>");
  }

  const repoRoot = (
    await runCommand("git", ["rev-parse", "--show-toplevel"])
  ).stdout.trim();
  const defaultRepo = await currentGitHubRepo(repoRoot);
  const issueRef = parseIssueInput(input, defaultRepo);
  const prd = await fetchIssue(issueRef.repo, issueRef.number, repoRoot);
  const branch = `feat/${prd.number}-${slugify(prd.title)}`;

  let lock: LockHandle | undefined;
  let neo4j: Neo4jRuntime | undefined;
  let sandbox: Sandbox | undefined;
  let success = false;

  try {
    lock = await acquireLock(repoRoot, branch, prd);

    const existingPr = await prepareBranchForPrd(
      repoRoot,
      issueRef.repo,
      branch,
      prd,
    );
    const plan = await buildSlicePlan(issueRef.repo, prd, repoRoot);

    if (plan.ordered.length === 0) {
      throw new Error(`No child slices labeled ready-for-agent for #${prd.number}.`);
    }

    await ensureSandcastleImage(repoRoot);
    const openCodeAuthPath = await requireOpenCodeAuth();
    neo4j = await startNeo4j(prd.number, repoRoot);

    sandbox = await createSandbox({
      branch,
      baseBranch: "origin/main",
      cwd: repoRoot,
      sandbox: docker({
        imageName: IMAGE_NAME,
        network: neo4j.networkName,
        mounts: [
          {
            hostPath: openCodeAuthPath,
            sandboxPath: "/home/agent/.local/share/opencode/auth.json",
            readonly: true,
          },
        ],
        env: {
          MEMORABLE_NEO4J_URI: "bolt://neo4j:7687",
          MEMORABLE_NEO4J_USER: NEO4J_USER,
          MEMORABLE_NEO4J_PASSWORD: NEO4J_PASSWORD,
        },
      }),
      hooks: {
        sandbox: {
          onSandboxReady: [
            { command: "uv sync --extra dev", timeoutMs: 600_000 },
          ],
        },
      },
      timeouts: { gitSetupMs: 60_000 },
    });

    console.log(`Sandcastle worktree: ${sandbox.worktreePath}`);

    const committedBySlice = await committedSliceCommits(
      sandbox.worktreePath,
      plan.ordered,
    );
    const priorState = await loadRunState(repoRoot, branch);
    const runState: RunState = {
      prd: prd.number,
      branch,
      updatedAt: new Date().toISOString(),
      slices: {},
    };

    const completed: CompletedSlice[] = [];
    const escalated: EscalatedSlice[] = [];
    const tainted = new Set<number>();

    for (const slice of plan.ordered) {
      const blockers = plan.blockersBySlice.get(slice.number) ?? [];
      const priorSliceState = priorState?.slices[slice.number];

      const existingCommit = committedBySlice.get(slice.number);
      if (existingCommit) {
        console.log(
          `Skipping #${slice.number}; already committed as ${existingCommit.slice(0, 12)}`,
        );
        completed.push({
          issue: slice,
          commitSha: existingCommit,
          review: {
            status: "clean",
            findings: priorSliceState?.lastFindings ?? [],
          },
        });
        runState.slices[slice.number] = {
          status: "done",
          commitSha: existingCommit,
          attempts: priorSliceState?.attempts ?? 0,
          lastFindings: priorSliceState?.lastFindings,
        };
        await persistRunState(repoRoot, branch, runState);
        continue;
      }

      if (
        priorSliceState &&
        (priorSliceState.status === "needs-human" ||
          priorSliceState.status === "blocked-upstream")
      ) {
        console.log(
          `Skipping #${slice.number}; previously escalated as ${priorSliceState.status} (not retrying).`,
        );
        const reason: EscalatedReason =
          priorSliceState.status === "blocked-upstream"
            ? "blocked-by-upstream-failure"
            : "needs-human";
        escalated.push({
          issue: slice,
          reason,
          detail: priorSliceState.reason ?? "Previously escalated; not retried.",
          findings: priorSliceState.lastFindings ?? [],
          attempts: priorSliceState.attempts,
        });
        tainted.add(slice.number);
        runState.slices[slice.number] = priorSliceState;
        await persistRunState(repoRoot, branch, runState);
        continue;
      }

      const taintedBlocker = blockers.find((blocker) => tainted.has(blocker));
      if (taintedBlocker !== undefined) {
        const detail = `Blocked by upstream failure: depends on escalated slice #${taintedBlocker}.`;
        console.log(`Skipping #${slice.number}; ${detail}`);
        escalated.push({
          issue: slice,
          reason: "blocked-by-upstream-failure",
          detail,
          findings: [],
          attempts: 0,
        });
        tainted.add(slice.number);
        runState.slices[slice.number] = {
          status: "blocked-upstream",
          attempts: 0,
          reason: detail,
        };
        await persistRunState(repoRoot, branch, runState);
        continue;
      }

      const outcome = await implementSlice({
        sandbox,
        repoRoot,
        branch,
        prd,
        slice,
        blockers,
        priorCompleted: completed,
        neo4j,
      });
      if (outcome.kind === "completed") {
        completed.push(outcome.completed);
        runState.slices[slice.number] = {
          status: "done",
          commitSha: outcome.completed.commitSha,
          attempts: 1,
          lastFindings: outcome.completed.review.findings,
        };
      } else {
        escalated.push(outcome.escalated);
        tainted.add(slice.number);
        runState.slices[slice.number] = {
          status: "needs-human",
          attempts: outcome.escalated.attempts,
          lastFindings: outcome.escalated.findings,
          reason: outcome.escalated.detail,
        };
      }
      await persistRunState(repoRoot, branch, runState);
    }

    let finalVerification = await runFinalVerification(sandbox.worktreePath, neo4j);
    if (!finalVerification.passed) {
      finalVerification = await stabilizeFinalVerification({
        sandbox,
        repoRoot,
        branch,
        prd,
        completed,
        initialFailure: finalVerification,
        neo4j,
      });
    }

    const architectReview = await runArchitectReview({
      sandbox,
      repoRoot,
      branch,
      prd,
      completed,
      skipped: plan.skipped,
      escalated,
      finalVerification,
    });

    await pushBranchWithGitHubToken({
      repo: issueRef.repo,
      branch,
      cwd: sandbox.worktreePath,
    });

    const draft =
      architectReview.status === "blocking_findings" || escalated.length > 0;
    const prBody = buildPullRequestBody({
      prd,
      completed,
      skipped: plan.skipped,
      escalated,
      finalVerification,
      architectReview,
    });
    const prTitle = `Implement #${prd.number}: ${prd.title}`;
    const pr = await upsertPullRequest({
      repo: issueRef.repo,
      branch,
      existingPr,
      title: prTitle,
      body: prBody,
      draft,
      cwd: repoRoot,
    });

    await commentOnPrdIssue({
      repo: issueRef.repo,
      prd,
      pr,
      completed,
      skipped: plan.skipped,
      escalated,
      cwd: repoRoot,
    });

    await sandbox.close();
    await cleanupNeo4j(neo4j, repoRoot);
    success = true;
    console.log(`PR ready: ${pr.url}`);
  } finally {
    if (!success) {
      if (sandbox) {
        console.error(`Preserving Sandcastle worktree: ${sandbox.worktreePath}`);
      }
      if (neo4j) {
        console.error(
          `Preserving Neo4j container ${neo4j.containerName} on network ${neo4j.networkName}`,
        );
        console.error(
          `Neo4j browser localhost:${neo4j.hostHttpPort}, bolt localhost:${neo4j.hostBoltPort}`,
        );
      }
    }
    if (lock) {
      await releaseLock(lock);
    }
  }
}

function parseIssueInput(input: string, defaultRepo: string) {
  const trimmed = input.trim();
  const urlMatch = /^https?:\/\/github\.com\/([^/]+\/[^/]+)\/issues\/(\d+)/.exec(
    trimmed,
  );
  if (urlMatch) {
    return { repo: urlMatch[1], number: Number(urlMatch[2]) };
  }

  const repoIssueMatch = /^([^\s/#]+\/[^\s#]+)#(\d+)$/.exec(trimmed);
  if (repoIssueMatch) {
    return { repo: repoIssueMatch[1], number: Number(repoIssueMatch[2]) };
  }

  const numberMatch = /^#?(\d+)$/.exec(trimmed);
  if (numberMatch) {
    return { repo: defaultRepo, number: Number(numberMatch[1]) };
  }

  throw new Error(`Could not parse PRD issue reference: ${input}`);
}

async function currentGitHubRepo(cwd: string) {
  return (
    await runCommand("gh", ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], {
      cwd,
    })
  ).stdout.trim();
}

async function fetchIssue(repo: string, number: number, cwd: string): Promise<Issue> {
  return ghJson<Issue>(
    [
      "issue",
      "view",
      String(number),
      "-R",
      repo,
      "--comments",
      "--json",
      "number,title,body,labels,state,comments,url",
    ],
    cwd,
  );
}

async function fetchIssueOptional(repo: string, number: number, cwd: string) {
  try {
    return await fetchIssue(repo, number, cwd);
  } catch (error) {
    if (error instanceof CommandFailed) {
      return undefined;
    }
    throw error;
  }
}

async function buildSlicePlan(
  repo: string,
  prd: Issue,
  cwd: string,
): Promise<SlicePlan> {
  const allReferenced = await ghJson<Issue[]>(
    [
      "issue",
      "list",
      "-R",
      repo,
      "--state",
      "all",
      "--limit",
      "200",
      "--search",
      `#${prd.number} in:body,comments`,
      "--json",
      "number,title,body,labels,state,comments,url",
    ],
    cwd,
  );

  const children = allReferenced
    .filter((issue) => issue.number !== prd.number)
    .filter((issue) => isChildOfPrd(issue, prd.number));

  const ready: Issue[] = [];
  const skipped: SkippedSlice[] = [];
  for (const issue of children) {
    const labels = labelSet(issue);
    if (labels.has("ready-for-agent")) {
      ready.push(issue);
      continue;
    }
    skipped.push({
      issue,
      reason: labels.has("ready-for-human")
        ? "ready-for-human"
        : "missing ready-for-agent",
    });
  }

  const childrenByNumber = new Map(children.map((issue) => [issue.number, issue]));
  const readyByNumber = new Map(ready.map((issue) => [issue.number, issue]));
  const blockersBySlice = new Map<number, number[]>();

  for (const slice of ready) {
    const blockers = extractBlockers(issueBody(slice));
    blockersBySlice.set(slice.number, blockers);
    for (const blockerNumber of blockers) {
      if (blockerNumber === slice.number) {
        throw new Error(`Slice #${slice.number} blocks itself.`);
      }
      if (readyByNumber.has(blockerNumber)) {
        continue;
      }
      const blocker =
        childrenByNumber.get(blockerNumber) ??
        (await fetchIssueOptional(repo, blockerNumber, cwd));
      if (!blocker) {
        throw new Error(
          `Slice #${slice.number} lists missing blocker #${blockerNumber}.`,
        );
      }
      if (blocker.state !== "CLOSED") {
        throw new Error(
          `Slice #${slice.number} is blocked by open issue #${blockerNumber}, which is not included in this run.`,
        );
      }
    }
  }

  return {
    ordered: topologicalOrder(ready, blockersBySlice),
    skipped,
    blockersBySlice,
  };
}

function isChildOfPrd(issue: Issue, prdNumber: number) {
  const text = issueText(issue);
  if (new RegExp(`\\bParent:\\s*#${prdNumber}\\b`, "i").test(text)) {
    return true;
  }

  const parentSection = extractMarkdownSection(text, "Parent");
  if (parentSection && issueRefs(parentSection).includes(prdNumber)) {
    return true;
  }

  return issueRefs(text).includes(prdNumber);
}

function topologicalOrder(issues: Issue[], blockersBySlice: Map<number, number[]>) {
  const issueByNumber = new Map(issues.map((issue) => [issue.number, issue]));
  const indegree = new Map(issues.map((issue) => [issue.number, 0]));
  const dependents = new Map<number, number[]>();

  for (const issue of issues) {
    for (const blocker of blockersBySlice.get(issue.number) ?? []) {
      if (!issueByNumber.has(blocker)) {
        continue;
      }
      indegree.set(issue.number, (indegree.get(issue.number) ?? 0) + 1);
      dependents.set(blocker, [...(dependents.get(blocker) ?? []), issue.number]);
    }
  }

  const queue = issues
    .filter((issue) => indegree.get(issue.number) === 0)
    .sort((a, b) => a.number - b.number);
  const ordered: Issue[] = [];

  while (queue.length > 0) {
    const issue = queue.shift();
    if (!issue) {
      break;
    }
    ordered.push(issue);
    for (const dependentNumber of dependents.get(issue.number) ?? []) {
      const nextDegree = (indegree.get(dependentNumber) ?? 0) - 1;
      indegree.set(dependentNumber, nextDegree);
      if (nextDegree === 0) {
        const dependent = issueByNumber.get(dependentNumber);
        if (dependent) {
          queue.push(dependent);
          queue.sort((a, b) => a.number - b.number);
        }
      }
    }
  }

  if (ordered.length !== issues.length) {
    const cycle = issues
      .filter((issue) => !ordered.some((done) => done.number === issue.number))
      .map((issue) => `#${issue.number}`)
      .join(", ");
    throw new Error(`Blocked-by cycle among ready slices: ${cycle}`);
  }

  return ordered;
}

async function prepareBranchForPrd(
  cwd: string,
  repo: string,
  branch: string,
  prd: Issue,
) {
  console.log(`Preparing branch ${branch} from origin/main`);
  await runCommand("git", ["fetch", "origin", "main"], { cwd, stream: true });

  const existingPr = await findOpenPullRequest(repo, branch, cwd);
  if (existingPr && !pullRequestReferencesPrd(existingPr, prd.number)) {
    throw new Error(
      `Open PR #${existingPr.number} already uses ${branch} but does not reference PRD #${prd.number}.`,
    );
  }

  const remoteExists = await commandSucceeds(
    "git",
    ["ls-remote", "--exit-code", "--heads", "origin", branch],
    { cwd },
  );
  if (remoteExists) {
    await runCommand(
      "git",
      ["fetch", "origin", `refs/heads/${branch}:refs/remotes/origin/${branch}`],
      { cwd, stream: true },
    );
  }

  const localExists = await commandSucceeds(
    "git",
    ["show-ref", "--verify", "--quiet", `refs/heads/${branch}`],
    { cwd },
  );

  if (remoteExists && !localExists) {
    await runCommand("git", ["branch", branch, `origin/${branch}`], { cwd });
  }

  if (remoteExists && localExists) {
    const containsRemote = await commandSucceeds(
      "git",
      ["merge-base", "--is-ancestor", `origin/${branch}`, branch],
      { cwd },
    );
    if (!containsRemote) {
      throw new Error(
        `Local ${branch} does not contain origin/${branch}; refusing to overwrite remote branch.`,
      );
    }
  }

  await ensureCheckedOutWorktreeClean(cwd, branch);
  return existingPr;
}

async function ensureCheckedOutWorktreeClean(cwd: string, branch: string) {
  const managedWorktreesDir = join(cwd, ".sandcastle", "worktrees");
  const output = (await runCommand("git", ["worktree", "list", "--porcelain"], { cwd }))
    .stdout;
  for (const worktree of parseWorktrees(output)) {
    if (worktree.branch !== branch) {
      continue;
    }
    if (!worktree.path.startsWith(`${managedWorktreesDir}/`)) {
      throw new Error(
        `Branch ${branch} is already checked out at ${worktree.path}; Sandcastle can only reuse managed worktrees under ${managedWorktreesDir}.`,
      );
    }
    const status = await gitStatus(worktree.path);
    if (status.trim()) {
      // A managed worktree with leftover changes is the signature of an
      // interrupted run. Commit the work-in-progress so the worktree is clean
      // and this run can resume from where the last one stopped, instead of
      // refusing to start.
      console.log(
        `Resuming: committing leftover work-in-progress in ${worktree.path}`,
      );
      await commitWorktreeWip(worktree.path, branch);
    }
  }
}

async function commitWorktreeWip(worktreePath: string, branch: string) {
  const status = await gitStatus(worktreePath);
  if (!status.trim()) {
    return null;
  }
  await runCommand("git", ["add", "-A"], { cwd: worktreePath });
  await runCommand(
    "git",
    ["commit", "--no-gpg-sign", "-m", `wip: resume ${branch}`],
    { cwd: worktreePath, stream: true },
  );
  return (await runCommand("git", ["rev-parse", "HEAD"], { cwd: worktreePath }))
    .stdout.trim();
}

function parseWorktrees(output: string) {
  return output
    .trim()
    .split(/\n\n+/)
    .filter(Boolean)
    .map((block) => {
      let path = "";
      let branch: string | undefined;
      for (const line of block.split("\n")) {
        if (line.startsWith("worktree ")) {
          path = line.slice("worktree ".length);
        }
        if (line.startsWith("branch refs/heads/")) {
          branch = line.slice("branch refs/heads/".length);
        }
      }
      return { path, branch };
    })
    .filter((worktree) => worktree.path);
}

async function acquireLock(
  repoRoot: string,
  branch: string,
  prd: Issue,
): Promise<LockHandle> {
  const locksDir = join(repoRoot, ".sandcastle", "locks");
  await mkdir(locksDir, { recursive: true });
  const lockPath = join(locksDir, `${branch.replace(/[^A-Za-z0-9._-]+/g, "_")}.lock`);
  try {
    await mkdir(lockPath);
  } catch (error) {
    const metadataPath = join(lockPath, "owner.json");
    let metadata = "";
    try {
      metadata = await readFile(metadataPath, "utf8");
    } catch {
      metadata = "no metadata";
    }
    throw new Error(`Sandcastle lock exists at ${lockPath}: ${metadata}`);
  }

  await writeFile(
    join(lockPath, "owner.json"),
    JSON.stringify(
      {
        pid: process.pid,
        prd: prd.number,
        branch,
        startedAt: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
  return { path: lockPath };
}

async function releaseLock(lock: LockHandle) {
  await rm(lock.path, { recursive: true, force: true });
}

async function ensureSandcastleImage(cwd: string) {
  const exists = await commandSucceeds("docker", ["image", "inspect", IMAGE_NAME], {
    cwd,
  });
  if (exists) {
    console.log(`Using Docker image ${IMAGE_NAME}`);
    return;
  }

  console.log(`Building Docker image ${IMAGE_NAME}`);
  await runCommand(
    "pnpm",
    [
      "exec",
      "sandcastle",
      "docker",
      "build-image",
      "--image-name",
      IMAGE_NAME,
      "--dockerfile",
      ".sandcastle/Dockerfile",
    ],
    { cwd, stream: true },
  );
}

async function requireOpenCodeAuth() {
  const authPath = join(homedir(), ".local", "share", "opencode", "auth.json");
  try {
    await access(authPath, constants.R_OK);
  } catch {
    throw new Error(
      `OpenCode OAuth auth not found at ${authPath}. Run opencode login on the host first.`,
    );
  }
  return authPath;
}

async function startNeo4j(prdNumber: number, cwd: string): Promise<Neo4jRuntime> {
  const suffix = `${prdNumber}-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const networkName = `memorable-prd-${suffix}`;
  const containerName = `memorable-neo4j-${suffix}`;

  try {
    await runCommand("docker", ["network", "create", networkName], { cwd, stream: true });
    await runCommand(
      "docker",
      [
        "run",
        "-d",
        "--name",
        containerName,
        "--network",
        networkName,
        "--network-alias",
        "neo4j",
        "-p",
        "0:7474",
        "-p",
        "0:7687",
        "-e",
        `NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}`,
        "-e",
        'NEO4J_PLUGINS=["apoc"]',
        "neo4j:5.26",
      ],
      { cwd, stream: true },
    );

    for (let attempt = 1; attempt <= 60; attempt += 1) {
      const ready = await commandSucceeds(
        "docker",
        [
          "exec",
          containerName,
          "cypher-shell",
          "-u",
          NEO4J_USER,
          "-p",
          NEO4J_PASSWORD,
          "RETURN 1",
        ],
        { cwd },
      );
      if (ready) {
        break;
      }
      if (attempt === 60) {
        throw new Error(`Neo4j did not become ready in ${containerName}.`);
      }
      await delay(2000);
    }

    const hostHttpPort = await dockerPort(containerName, "7474/tcp", cwd);
    const hostBoltPort = await dockerPort(containerName, "7687/tcp", cwd);
    console.log(
      `Neo4j ready: container=${containerName}, network=${networkName}, browser=localhost:${hostHttpPort}, bolt=localhost:${hostBoltPort}`,
    );
    return { containerName, networkName, hostHttpPort, hostBoltPort };
  } catch (error) {
    console.error(
      `Neo4j startup failed; preserving container ${containerName} and network ${networkName} if they were created.`,
    );
    throw error;
  }
}

async function dockerPort(containerName: string, port: string, cwd: string) {
  const output = (
    await runCommand("docker", ["port", containerName, port], { cwd })
  ).stdout.trim();
  const match = /:(\d+)$/.exec(output);
  if (!match) {
    throw new Error(`Could not parse Docker port output for ${containerName}: ${output}`);
  }
  return match[1];
}

async function cleanupNeo4j(neo4j: Neo4jRuntime, cwd: string) {
  await runCommand("docker", ["rm", "-f", neo4j.containerName], {
    cwd,
    allowFailure: true,
    stream: true,
  });
  await runCommand("docker", ["network", "rm", neo4j.networkName], {
    cwd,
    allowFailure: true,
    stream: true,
  });
}

function stateFilePath(repoRoot: string, branch: string) {
  return join(
    repoRoot,
    ".sandcastle",
    "state",
    `${sanitizeLogBranch(branch)}.json`,
  );
}

async function loadRunState(
  repoRoot: string,
  branch: string,
): Promise<RunState | undefined> {
  try {
    const raw = await readFile(stateFilePath(repoRoot, branch), "utf8");
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed) || !isRecord(parsed.slices)) {
      return undefined;
    }
    const slices: Record<number, SliceState> = {};
    for (const [key, value] of Object.entries(parsed.slices)) {
      if (!isRecord(value)) {
        continue;
      }
      const status = value.status;
      if (
        status !== "done" &&
        status !== "needs-human" &&
        status !== "blocked-upstream" &&
        status !== "pending"
      ) {
        continue;
      }
      slices[Number(key)] = {
        status,
        commitSha: typeof value.commitSha === "string" ? value.commitSha : undefined,
        attempts: typeof value.attempts === "number" ? value.attempts : 0,
        lastFindings: Array.isArray(value.lastFindings)
          ? value.lastFindings.map(normalizeFinding)
          : undefined,
        reason: typeof value.reason === "string" ? value.reason : undefined,
      };
    }
    return {
      prd: typeof parsed.prd === "number" ? parsed.prd : 0,
      branch: typeof parsed.branch === "string" ? parsed.branch : branch,
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : "",
      slices,
    };
  } catch {
    return undefined;
  }
}

async function persistRunState(
  repoRoot: string,
  branch: string,
  state: RunState,
) {
  state.updatedAt = new Date().toISOString();
  const path = stateFilePath(repoRoot, branch);
  await mkdir(join(repoRoot, ".sandcastle", "state"), { recursive: true });
  await writeFile(path, `${JSON.stringify(state, null, 2)}\n`);
}

async function implementSlice(args: {
  sandbox: Sandbox;
  repoRoot: string;
  branch: string;
  prd: Issue;
  slice: Issue;
  blockers: number[];
  priorCompleted: CompletedSlice[];
  neo4j: Neo4jRuntime;
}): Promise<SliceOutcome> {
  const { sandbox, repoRoot, branch, prd, slice, blockers, priorCompleted, neo4j } = args;
  let feedback = "";
  let lastReview: ReviewResult | undefined;
  const priorAttempts: PriorAttempt[] = [];
  let attempts = 0;

  for (let attempt = 1; attempt <= MAX_SLICE_ATTEMPTS; attempt += 1) {
    attempts = attempt;
    console.log(
      `Implementing #${slice.number} attempt ${attempt}/${MAX_SLICE_ATTEMPTS}`,
    );
    const implementRunName = `implement-${slice.number}-${attempt}`;
    const implementResult = await sandbox.run({
      agent: opencode(MODEL, { variant: IMPLEMENTER_VARIANT }),
      prompt: buildImplementerPrompt({
        prd,
        slice,
        blockers,
        priorCompleted,
        feedback,
      }),
      name: implementRunName,
      logging: agentLogging(repoRoot, branch, implementRunName),
      completionSignal: COMPLETION_SIGNAL,
      idleTimeoutSeconds: 1_200,
      completionTimeoutSeconds: 90,
    });
    assertAgentDidNotCommit(implementResult, `implementer for #${slice.number}`);

    await includeUntrackedFilesInReviewDiff(sandbox.worktreePath);
    const beforeReviewStatus = await gitStatus(sandbox.worktreePath);
    const reviewRunName = `review-${slice.number}-${attempt}`;
    const reviewResult = await sandbox.run({
      agent: opencode(MODEL, { variant: REVIEWER_VARIANT }),
      prompt: buildSliceReviewPrompt(prd, slice, priorAttempts),
      name: reviewRunName,
      logging: agentLogging(repoRoot, branch, reviewRunName),
      completionSignal: COMPLETION_SIGNAL,
      idleTimeoutSeconds: 900,
      completionTimeoutSeconds: 90,
    });
    assertAgentDidNotCommit(reviewResult, `reviewer for #${slice.number}`);
    const afterReviewStatus = await gitStatus(sandbox.worktreePath);
    if (afterReviewStatus !== beforeReviewStatus) {
      throw new Error(
        `Reviewer for #${slice.number} modified the worktree; preserving for inspection.`,
      );
    }

    lastReview = parseReviewOutput(reviewResult.stdout, "review_json");

    if (lastReview.status === "blocked_on_upstream") {
      console.log(
        `Reviewer marked #${slice.number} blocked_on_upstream; escalating without further retries.`,
      );
      await commitBlockedSlice(sandbox.worktreePath, slice);
      return {
        kind: "escalated",
        escalated: {
          issue: slice,
          reason: "needs-human",
          detail: `Reviewer returned blocked_on_upstream:\n${formatFindings(
            lastReview.findings,
          )}`,
          findings: lastReview.findings,
          attempts,
        },
      };
    }

    if (lastReview.status === "blocking_findings") {
      const direction = `Previous review found blocking issues:\n${formatFindings(
        lastReview.findings,
      )}`;
      priorAttempts.push({
        attempt,
        status: lastReview.status,
        findings: lastReview.findings,
        direction,
      });
      if (attempt === MAX_SLICE_ATTEMPTS) {
        console.log(
          `Blocking review findings remain for #${slice.number} after ${MAX_SLICE_ATTEMPTS} attempts; escalating.`,
        );
        await commitBlockedSlice(sandbox.worktreePath, slice);
        return {
          kind: "escalated",
          escalated: {
            issue: slice,
            reason: "needs-human",
            detail: `Blocking review findings remain after ${MAX_SLICE_ATTEMPTS} attempts:\n${formatFindings(
              lastReview.findings,
            )}`,
            findings: lastReview.findings,
            attempts,
          },
        };
      }
      feedback = direction;
      continue;
    }

    const verification = await runPerSliceVerification(sandbox.worktreePath, neo4j);
    if (!verification.passed) {
      const direction = `Previous verification failed:\n${formatVerificationFailure(
        verification,
      )}`;
      priorAttempts.push({
        attempt,
        status: lastReview.status,
        findings: lastReview.findings,
        direction,
      });
      if (attempt === MAX_SLICE_ATTEMPTS) {
        console.log(
          `Per-slice verification failed for #${slice.number} after ${MAX_SLICE_ATTEMPTS} attempts; escalating.`,
        );
        await commitBlockedSlice(sandbox.worktreePath, slice);
        return {
          kind: "escalated",
          escalated: {
            issue: slice,
            reason: "needs-human",
            detail: `Per-slice verification failed after ${MAX_SLICE_ATTEMPTS} attempts:\n${formatVerificationFailure(
              verification,
            )}`,
            findings: lastReview.findings,
            attempts,
          },
        };
      }
      feedback = direction;
      continue;
    }

    const commitSha = await commitSlice(sandbox.worktreePath, slice);
    return {
      kind: "completed",
      completed: { issue: slice, commitSha, review: lastReview },
    };
  }

  throw new Error(`Unexpected implementation loop exit for #${slice.number}.`);
}

function buildImplementerPrompt(args: {
  prd: Issue;
  slice: Issue;
  blockers: number[];
  priorCompleted: CompletedSlice[];
  feedback: string;
}) {
  const { prd, slice, blockers, priorCompleted, feedback } = args;
  return `You are implementing a Memorable PRD slice inside a Docker sandbox.

## Parent PRD: ${prd.title} (#${prd.number})

${issueBody(prd)}

## Current Slice: ${slice.title} (#${slice.number})

${issueBody(slice)}

## Slice Comments

${formatComments(slice)}

## Blockers Already Satisfied

${blockers.length > 0 ? blockers.map((number) => `- #${number}`).join("\n") : "None"}

## Prior Completed Slices In This PRD Run

${
  priorCompleted.length > 0
    ? priorCompleted
        .map(
          (done) =>
            `- #${done.issue.number} ${done.issue.title} (${done.commitSha.slice(0, 12)})`,
        )
        .join("\n")
    : "None"
}

## Feedback To Address

${feedback || "None"}

## Constraints

- Implement only slice #${slice.number}; do not inspect or anticipate future slices.
- Do not commit. The host orchestrator owns all commits.
- Do not use gh or mutate GitHub issues, PRs, labels, or comments.
- When a review finding offers a fork ("do X OR remove Y"), pick the MINIMAL in-scope fix. Prefer removing/narrowing over adding.
- NEVER expand scope to satisfy a review: do not add new core services, ports, storage methods, or subsystems. Stay inside slice #${slice.number}.
- If a finding can only be resolved by upstream or out-of-slice work, do the minimal in-scope thing and state clearly in your summary that the finding requires an upstream slice / spec fix (so the reviewer can return blocked_on_upstream instead of blocking it).
- Follow the TDD philosophy in .claude/skills/tdd/SKILL.md: behavior through public interfaces, vertical tracer bullets, minimal implementation.
- For this AFK PRD factory, skip RED/GREEN commit discipline because you must not commit.
- If you touch Memorable product model or domain language, read docs/product.md, docs/ubiquitous-language.md, and relevant ADRs first.
- Neo4j is available at MEMORABLE_NEO4J_URI with MEMORABLE_NEO4J_USER and MEMORABLE_NEO4J_PASSWORD.
- Run narrow tests while working. Use uv run --extra dev ... for ruff and pytest commands because dev tools live in the dev extra.
- The orchestrator will run ruff and pytest before committing.

## Progress Output

${AGENT_PROGRESS_INSTRUCTIONS}

When finished, summarize changed behavior and print ${COMPLETION_SIGNAL}.`;
}

function buildSliceReviewPrompt(
  prd: Issue,
  slice: Issue,
  priorAttempts: PriorAttempt[],
) {
  return `You are reviewing the current worktree diff for Memorable slice #${slice.number}.

## Parent PRD

#${prd.number} ${prd.title}

## Slice

#${slice.number} ${slice.title}

${issueBody(slice)}

## Prior Review Attempts For This Slice

${formatPriorAttempts(priorAttempts)}

## Instructions

- Review only. Do not modify files. Do not commit. Do not use gh.
- Review the current diff against origin/main, focused on slice #${slice.number}.
- Untracked files are part of the slice: the orchestrator runs git add -A before committing, and marks untracked files intent-to-add before review so they appear in diffs.
- Do not report a file as blocking solely because it is untracked; review its contents instead.
- Apply Memorable review rules from .claude/skills/project-code-review/RULES.md.
- Treat missing behavior tests, domain-language leaks, boundary duplication, or failing verification risks as blocking when they can break the slice.
- Do NOT reverse a direction the implementer followed on your previous advice. Do NOT introduce a new, contradictory blocking direction on a late attempt. If your concern is that earlier advice was wrong, say so explicitly and prefer escalation over whipsawing.
- Do NOT propose "build a new subsystem" or "add a new core service/port/storage method" as an in-scope fix. Scope-expanding fixes are an upstream gap, not a slice defect.
- If this slice cannot be satisfied as specified without upstream work or a spec fix (i.e. retrying the implementer cannot help), return status "blocked_on_upstream" instead of "blocking_findings". Reserve "blocking_findings" for problems the implementer can fix inside slice #${slice.number}.
- Use uv run --extra dev ... for ruff and pytest commands because dev tools live in the dev extra.
- Keep the terminal informative using the progress output rules below.
- Return structured JSON inside <review_json> tags, then print ${COMPLETION_SIGNAL}.

## Progress Output

${AGENT_PROGRESS_INSTRUCTIONS}

Schema:
<review_json>
{
  "status": "clean" | "non_blocking_findings" | "blocking_findings" | "blocked_on_upstream",
  "findings": [
    { "severity": "blocking" | "non_blocking", "file": "path or null", "line": 1, "fix": "specific fix" }
  ]
}
</review_json>

Use "blocked_on_upstream" when the slice as specified requires upstream/out-of-slice work or a spec correction and no in-slice change by the implementer can resolve it.`;
}

function formatPriorAttempts(priorAttempts: PriorAttempt[]) {
  if (priorAttempts.length === 0) {
    return "None. This is the first review attempt.";
  }
  return priorAttempts
    .map(
      (prior) =>
        `### Attempt ${prior.attempt} (status: ${prior.status})\nFindings:\n${formatFindings(
          prior.findings,
        )}\nDirection the implementer was told to follow:\n${prior.direction}`,
    )
    .join("\n\n");
}

async function runPerSliceVerification(
  worktreePath: string,
  neo4j: Neo4jRuntime,
) {
  return runChecks(worktreePath, [
    { command: "uv", args: ["run", "--extra", "dev", "ruff", "check", "."] },
    {
      command: "uv",
      args: ["run", "--extra", "dev", "pytest", "tests/", "-v", "--tb=short"],
      env: hostNeo4jEnv(neo4j),
    },
  ]);
}

async function runFinalVerification(worktreePath: string, neo4j: Neo4jRuntime) {
  console.log("Running final verification");
  return runChecks(worktreePath, [
    { command: "uv", args: ["run", "--extra", "dev", "ruff", "check", "."] },
    {
      command: "uv",
      args: ["run", "--extra", "dev", "ruff", "format", "--check", "."],
    },
    {
      command: "uv",
      args: ["run", "--extra", "dev", "pytest", "-x", "-q", "-m", "not integration"],
    },
    {
      command: "uv",
      args: ["run", "--extra", "dev", "pytest", "-x", "-q", "-m", "integration"],
      env: hostNeo4jEnv(neo4j),
    },
  ]);
}

async function stabilizeFinalVerification(args: {
  sandbox: Sandbox;
  repoRoot: string;
  branch: string;
  prd: Issue;
  completed: CompletedSlice[];
  initialFailure: VerificationSummary;
  neo4j: Neo4jRuntime;
}) {
  const { sandbox, repoRoot, branch, prd, completed, neo4j } = args;
  let failure = args.initialFailure;

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    console.log(`Final stabilization attempt ${attempt}/2`);
    const runName = `stabilize-${attempt}`;
    const result = await sandbox.run({
      agent: opencode(MODEL, { variant: IMPLEMENTER_VARIANT }),
      prompt: buildStabilizationPrompt(prd, completed, failure),
      name: runName,
      logging: agentLogging(repoRoot, branch, runName),
      completionSignal: COMPLETION_SIGNAL,
      idleTimeoutSeconds: 1_200,
      completionTimeoutSeconds: 90,
    });
    assertAgentDidNotCommit(result, "final stabilizer");

    const verification = await runFinalVerification(sandbox.worktreePath, neo4j);
    if (verification.passed) {
      const status = await gitStatus(sandbox.worktreePath);
      if (status.trim()) {
        await runCommand("git", ["add", "-A"], { cwd: sandbox.worktreePath });
        await runCommand(
          "git",
          [
            "commit",
            "--no-gpg-sign",
            "-m",
            `fix: stabilize #${prd.number} verification`,
            "-m",
            `Refs #${prd.number}`,
          ],
          { cwd: sandbox.worktreePath, stream: true },
        );
      }
      return verification;
    }
    failure = verification;
  }

  throw new Error(
    `Final verification still failing after stabilization:\n${formatVerificationFailure(
      failure,
    )}`,
  );
}

function buildStabilizationPrompt(
  prd: Issue,
  completed: CompletedSlice[],
  failure: VerificationSummary,
) {
  return `Final verification failed after all PRD slices were implemented.

## Parent PRD

#${prd.number} ${prd.title}

## Completed Slices

${completed
  .map((done) => `- #${done.issue.number} ${done.issue.title} (${done.commitSha.slice(0, 12)})`)
  .join("\n")}

## Verification Failure

${formatVerificationFailure(failure)}

## Constraints

- Fix only issues needed to make final verification pass.
- Do not add new product scope.
- Do not commit. The host orchestrator owns commits.
- Do not use gh or mutate GitHub.
- Use uv run --extra dev ... for ruff and pytest commands because dev tools live in the dev extra.

## Progress Output

${AGENT_PROGRESS_INSTRUCTIONS}

When finished, summarize changed behavior and print ${COMPLETION_SIGNAL}.`;
}

async function runArchitectReview(args: {
  sandbox: Sandbox;
  repoRoot: string;
  branch: string;
  prd: Issue;
  completed: CompletedSlice[];
  skipped: SkippedSlice[];
  escalated: EscalatedSlice[];
  finalVerification: VerificationSummary;
}) {
  console.log("Running final architect review");
  const architectGuide = await readFile(
    join(args.repoRoot, ".claude", "agents", "architect.md"),
    "utf8",
  );
  const beforeReviewStatus = await gitStatus(args.sandbox.worktreePath);
  const runName = "architect-review";
  const result = await args.sandbox.run({
    agent: opencode(MODEL, { variant: REVIEWER_VARIANT }),
    prompt: buildArchitectPrompt({ ...args, architectGuide }),
    name: runName,
    logging: agentLogging(args.repoRoot, args.branch, runName),
    completionSignal: COMPLETION_SIGNAL,
    idleTimeoutSeconds: 900,
    completionTimeoutSeconds: 90,
  });
  assertAgentDidNotCommit(result, "architect reviewer");
  const afterReviewStatus = await gitStatus(args.sandbox.worktreePath);
  if (afterReviewStatus !== beforeReviewStatus) {
    throw new Error("Architect reviewer modified the worktree; preserving for inspection.");
  }

  try {
    return parseReviewOutput(result.stdout, "architect_review_json");
  } catch (error) {
    return {
      status: "blocking_findings" as const,
      findings: [
        {
          severity: "blocking",
          file: null,
          line: null,
          fix: `Architect review output was not parseable: ${
            error instanceof Error ? error.message : String(error)
          }`,
        },
      ],
    };
  }
}

function buildArchitectPrompt(args: {
  prd: Issue;
  completed: CompletedSlice[];
  skipped: SkippedSlice[];
  escalated: EscalatedSlice[];
  finalVerification: VerificationSummary;
  architectGuide: string;
}) {
  return `You are Memorable's final architecture reviewer. Review only; do not modify files, commit, or use gh.

## Architect Perspective

${args.architectGuide}

## Parent PRD

#${args.prd.number} ${args.prd.title}

${issueBody(args.prd)}

## Completed Slices

${args.completed
  .map((done) => `- #${done.issue.number} ${done.issue.title} (${done.commitSha.slice(0, 12)})`)
  .join("\n")}

## Skipped Slices

${
  args.skipped.length > 0
    ? args.skipped
        .map((skipped) => `- #${skipped.issue.number} ${skipped.issue.title}: ${skipped.reason}`)
        .join("\n")
    : "None"
}

## Escalated Slices (needs-human / blocked-upstream)

${formatEscalatedForPrompt(args.escalated)}

## Verification

${formatVerificationSummary(args.finalVerification)}

## Instructions

- This is a PARTIAL run if any slices were escalated. Review the completed work as-is; do not block solely because escalated slices are missing.
- Review the whole branch diff against origin/main.
- Focus on architecture, product semantics, temporal semantics, domain language, tests, and maintainability.
- Do not auto-fix anything.
- Use uv run --extra dev ... for ruff and pytest commands because dev tools live in the dev extra.
- Keep the terminal informative using the progress output rules below.
- Return structured JSON inside <architect_review_json> tags, then print ${COMPLETION_SIGNAL}.

## Progress Output

${AGENT_PROGRESS_INSTRUCTIONS}

Schema:
<architect_review_json>
{
  "status": "clean" | "non_blocking_findings" | "blocking_findings",
  "findings": [
    { "severity": "blocking" | "non_blocking", "file": "path or null", "line": 1, "fix": "specific fix" }
  ]
}
</architect_review_json>`;
}

function agentLogging(
  repoRoot: string,
  branch: string,
  name: string,
): LoggingOption {
  return {
    type: "file",
    path: join(
      repoRoot,
      ".sandcastle",
      "logs",
      `${sanitizeLogBranch(branch)}-${sanitizeLogName(name)}.log`,
    ),
    onAgentStreamEvent: createAgentProgressPrinter(name),
  };
}

function createAgentProgressPrinter(name: string) {
  return (event: AgentStreamEvent) => {
    if (event.type === "toolCall") {
      console.log(
        `[${name}] ${event.name}: ${shorten(oneLine(event.formattedArgs), 220)}`,
      );
      return;
    }

    for (const line of agentTextLines(event.message)) {
      console.log(`[${name}] ${shorten(line, 500)}`);
    }
  };
}

function agentTextLines(message: string) {
  return message
    .replaceAll(COMPLETION_SIGNAL, "")
    .split(/\r?\n/)
    .map(oneLine)
    .filter((line) => line.length > 0);
}

function sanitizeLogBranch(value: string) {
  return value.replace(/[/\\:*?"<>|]/g, "-");
}

function sanitizeLogName(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9_.-]/g, "-");
}

function shorten(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

async function runChecks(
  cwd: string,
  checks: { command: string; args: string[]; env?: Record<string, string> }[],
): Promise<VerificationSummary> {
  const results: CheckResult[] = [];
  for (const check of checks) {
    const result = await runCommand(check.command, check.args, {
      cwd,
      env: check.env,
      allowFailure: true,
      stream: true,
    });
    results.push({
      command: formatCheckCommand(result.command, check.env),
      exitCode: result.exitCode,
      stdout: result.stdout,
      stderr: result.stderr,
    });
    if (result.exitCode !== 0) {
      return { passed: false, checks: results };
    }
  }
  return { passed: true, checks: results };
}

function formatCheckCommand(command: string, env?: Record<string, string>) {
  if (!env || Object.keys(env).length === 0) {
    return command;
  }
  return `${Object.entries(env)
    .map(([key, value]) => `${key}=${shellDisplayQuote(value)}`)
    .join(" ")} ${command}`;
}

function hostNeo4jEnv(neo4j: Neo4jRuntime) {
  return {
    MEMORABLE_NEO4J_URI: `bolt://localhost:${neo4j.hostBoltPort}`,
    MEMORABLE_NEO4J_USER: NEO4J_USER,
    MEMORABLE_NEO4J_PASSWORD: NEO4J_PASSWORD,
  };
}

async function commitSlice(worktreePath: string, slice: Issue) {
  const status = await gitStatus(worktreePath);
  if (!status.trim()) {
    throw new Error(`Slice #${slice.number} produced no changes.`);
  }

  await runCommand("git", ["add", "-A"], { cwd: worktreePath });
  await runCommand(
    "git",
    [
      "commit",
      "--no-gpg-sign",
      "-m",
      `feat: implement #${slice.number} - ${oneLine(slice.title)}`,
      "-m",
      `Closes #${slice.number}`,
    ],
    { cwd: worktreePath, stream: true },
  );
  return (await runCommand("git", ["rev-parse", "HEAD"], { cwd: worktreePath }))
    .stdout.trim();
}

async function commitBlockedSlice(worktreePath: string, slice: Issue) {
  const status = await gitStatus(worktreePath);
  if (!status.trim()) {
    return;
  }
  await runCommand("git", ["add", "-A"], { cwd: worktreePath });
  await runCommand(
    "git",
    [
      "commit",
      "--no-gpg-sign",
      "-m",
      `wip: blocked #${slice.number} (needs-human)`,
      "-m",
      `Refs #${slice.number}`,
    ],
    { cwd: worktreePath, stream: true },
  );
}

async function committedSliceCommits(
  worktreePath: string,
  slices: Issue[],
) {
  const result = await runCommand(
    "git",
    ["log", "--reverse", "--format=%H%x00%s%x00%b%x1e", "origin/main..HEAD"],
    { cwd: worktreePath, allowFailure: true },
  );
  const commits = result.stdout
    .split("\x1e")
    .map((record) => record.trim())
    .filter((record) => record.length > 0)
    .map((record) => {
      const [sha = "", subject = "", body = ""] = record.split("\x00");
      return { sha, text: `${subject}\n${body}` };
    });
  const bySlice = new Map<number, string>();
  for (const slice of slices) {
    const issuePattern = new RegExp(`(^|\\D)#${slice.number}(\\D|$)`);
    const commit = commits.find((item) => issuePattern.test(item.text));
    if (commit?.sha) {
      bySlice.set(slice.number, commit.sha);
    }
  }
  return bySlice;
}

async function gitStatus(cwd: string) {
  return (await runCommand("git", ["status", "--porcelain"], { cwd })).stdout;
}

async function pushBranchWithGitHubToken(args: {
  repo: string;
  branch: string;
  cwd: string;
}) {
  const token = (await runCommand("gh", ["auth", "token"], { cwd: args.cwd })).stdout.trim();
  if (!token) {
    throw new Error("gh auth token returned no token; run gh auth login first.");
  }

  const auth = Buffer.from(`x-access-token:${token}`).toString("base64");
  await runCommand(
    "git",
    [
      "push",
      `https://github.com/${args.repo}.git`,
      `HEAD:refs/heads/${args.branch}`,
    ],
    {
      cwd: args.cwd,
      env: {
        GIT_CONFIG_COUNT: "1",
        GIT_CONFIG_KEY_0: "http.extraheader",
        GIT_CONFIG_VALUE_0: `AUTHORIZATION: Basic ${auth}`,
      },
      stream: true,
    },
  );
}

async function includeUntrackedFilesInReviewDiff(cwd: string) {
  await runCommand("git", ["add", "-N", "--", "."], { cwd });
}

function assertAgentDidNotCommit(result: SandboxRunResult, role: string) {
  if (result.commits.length > 0) {
    throw new Error(
      `${role} created commit(s): ${result.commits
        .map((commit) => commit.sha)
        .join(", ")}. Preserving worktree for inspection.`,
    );
  }
}

async function findOpenPullRequest(repo: string, branch: string, cwd: string) {
  const prs = await ghJson<PullRequest[]>(
    [
      "pr",
      "list",
      "-R",
      repo,
      "--head",
      branch,
      "--state",
      "open",
      "--json",
      "number,url,title,body,isDraft",
    ],
    cwd,
  );
  if (prs.length > 1) {
    throw new Error(`Multiple open PRs found for ${branch}: ${prs.map((pr) => pr.url).join(", ")}`);
  }
  return prs[0];
}

function pullRequestReferencesPrd(pr: PullRequest, prdNumber: number) {
  return `${pr.title}\n${pr.body ?? ""}`.includes(`#${prdNumber}`);
}

async function upsertPullRequest(args: {
  repo: string;
  branch: string;
  existingPr?: PullRequest;
  title: string;
  body: string;
  draft: boolean;
  cwd: string;
}): Promise<PullRequest> {
  if (args.existingPr) {
    await runCommand(
      "gh",
      [
        "pr",
        "edit",
        String(args.existingPr.number),
        "-R",
        args.repo,
        "--title",
        args.title,
        "--body-file",
        "-",
      ],
      { cwd: args.cwd, input: args.body, stream: true },
    );
    await syncDraftState(args.existingPr, args.draft, args.repo, args.cwd);
    return { ...args.existingPr, title: args.title, body: args.body, isDraft: args.draft };
  }

  const commandArgs = [
    "pr",
    "create",
    "-R",
    args.repo,
    "--base",
    "main",
    "--head",
    args.branch,
    "--title",
    args.title,
    "--body-file",
    "-",
  ];
  if (args.draft) {
    commandArgs.push("--draft");
  }
  const output = await runCommand("gh", commandArgs, {
    cwd: args.cwd,
    input: args.body,
    stream: true,
  });
  return {
    number: 0,
    url: output.stdout.trim(),
    title: args.title,
    body: args.body,
    isDraft: args.draft,
  };
}

async function syncDraftState(
  pr: PullRequest,
  shouldBeDraft: boolean,
  repo: string,
  cwd: string,
) {
  if (shouldBeDraft && !pr.isDraft) {
    await runCommand("gh", ["pr", "ready", String(pr.number), "-R", repo, "--undo"], {
      cwd,
      stream: true,
    });
  }
  if (!shouldBeDraft && pr.isDraft) {
    await runCommand("gh", ["pr", "ready", String(pr.number), "-R", repo], {
      cwd,
      stream: true,
    });
  }
}

async function commentOnPrdIssue(args: {
  repo: string;
  prd: Issue;
  pr: PullRequest;
  completed: CompletedSlice[];
  skipped: SkippedSlice[];
  escalated: EscalatedSlice[];
  cwd: string;
}) {
  const implemented = args.completed.map((done) => `#${done.issue.number}`).join(", ");
  const skipped = args.skipped.map((item) => `#${item.issue.number}`).join(", ");
  const needsHuman = args.escalated
    .filter((item) => item.reason === "needs-human")
    .map((item) => `#${item.issue.number}`)
    .join(", ");
  const blockedUpstream = args.escalated
    .filter((item) => item.reason === "blocked-by-upstream-failure")
    .map((item) => `#${item.issue.number}`)
    .join(", ");
  const body =
    `Opened PR ${args.pr.url} implementing ${implemented || "none"}. ` +
    `Skipped (labels): ${skipped || "none"}. ` +
    `Escalated needs-human: ${needsHuman || "none"}. ` +
    `Blocked by upstream failure: ${blockedUpstream || "none"}.`;
  await runCommand(
    "gh",
    ["issue", "comment", String(args.prd.number), "-R", args.repo, "--body-file", "-"],
    { cwd: args.cwd, input: body, stream: true },
  );
}

function formatEscalatedForPrompt(escalated: EscalatedSlice[]) {
  if (escalated.length === 0) {
    return "None";
  }
  return escalated
    .map(
      (item) =>
        `- #${item.issue.number} ${item.issue.title} (${item.reason}): ${oneLine(item.detail)}`,
    )
    .join("\n");
}

function formatEscalatedForBody(escalated: EscalatedSlice[]) {
  const needsHuman = escalated.filter((item) => item.reason === "needs-human");
  const blockedUpstream = escalated.filter(
    (item) => item.reason === "blocked-by-upstream-failure",
  );
  const sections: string[] = [];
  sections.push(
    `### Needs Human\n\n${
      needsHuman.length > 0
        ? needsHuman
            .map(
              (item) =>
                `- #${item.issue.number} ${item.issue.title} (after ${item.attempts} attempt(s)): ${oneLine(
                  item.detail,
                )}`,
            )
            .join("\n")
        : "None"
    }`,
  );
  sections.push(
    `### Blocked By Upstream Failure\n\n${
      blockedUpstream.length > 0
        ? blockedUpstream
            .map(
              (item) =>
                `- #${item.issue.number} ${item.issue.title}: ${oneLine(item.detail)}`,
            )
            .join("\n")
        : "None"
    }`,
  );
  return sections.join("\n\n");
}

function buildPullRequestBody(args: {
  prd: Issue;
  completed: CompletedSlice[];
  skipped: SkippedSlice[];
  escalated: EscalatedSlice[];
  finalVerification: VerificationSummary;
  architectReview: ReviewResult;
}) {
  const prdKeyword =
    args.skipped.length === 0 && args.escalated.length === 0 ? "Closes" : "Refs";
  const nonBlocking = args.completed.flatMap((done) =>
    done.review.status === "non_blocking_findings"
      ? done.review.findings.map((finding) => ({ slice: done.issue, finding }))
      : [],
  );

  return `## PRD

${prdKeyword} #${args.prd.number}

## Completed Slices

${args.completed
  .map(
    (done) =>
      `- Closes #${done.issue.number} - ${done.issue.title} (${done.commitSha.slice(0, 12)})`,
  )
  .join("\n")}

## Skipped Slices

${
  args.skipped.length > 0
    ? args.skipped
        .map((skipped) => `- #${skipped.issue.number} - ${skipped.issue.title}: ${skipped.reason}`)
        .join("\n")
    : "None"
}

## Escalated Slices

${formatEscalatedForBody(args.escalated)}

## Verification

${formatVerificationSummary(args.finalVerification)}

## Known Non-Blocking Review Notes

${
  nonBlocking.length > 0
    ? nonBlocking
        .map(
          ({ slice, finding }) =>
            `- #${slice.number} ${finding.file ?? "general"}${
              finding.line ? `:${finding.line}` : ""
            } - ${finding.fix}`,
        )
        .join("\n")
    : "None"
}

## Architect Review

Status: ${args.architectReview.status}

${
  args.architectReview.findings.length > 0
    ? formatFindings(args.architectReview.findings)
    : "No findings."
}`;
}

function parseReviewOutput(stdout: string, tag: string): ReviewResult {
  const content = extractTaggedContent(stdout, tag) ?? extractJsonObject(stdout);
  if (!content) {
    throw new Error(`Could not find <${tag}> JSON in reviewer output.`);
  }
  const parsed = JSON.parse(stripJsonFence(content)) as unknown;
  if (!isRecord(parsed)) {
    throw new Error("Review JSON was not an object.");
  }
  const status = parsed.status;
  if (
    status !== "clean" &&
    status !== "non_blocking_findings" &&
    status !== "blocking_findings" &&
    status !== "blocked_on_upstream"
  ) {
    throw new Error(`Invalid review status: ${String(status)}`);
  }
  const rawFindings = Array.isArray(parsed.findings) ? parsed.findings : [];
  return {
    status,
    findings: rawFindings.map(normalizeFinding),
  };
}

function normalizeFinding(finding: unknown): ReviewFinding {
  if (!isRecord(finding)) {
    return { severity: "blocking", file: null, line: null, fix: String(finding) };
  }
  const line = typeof finding.line === "number" ? finding.line : null;
  return {
    severity: typeof finding.severity === "string" ? finding.severity : "blocking",
    file: typeof finding.file === "string" ? finding.file : null,
    line,
    fix: typeof finding.fix === "string" ? finding.fix : JSON.stringify(finding),
  };
}

function extractTaggedContent(stdout: string, tag: string) {
  const match = new RegExp(`<${tag}>\\s*([\\s\\S]*?)\\s*</${tag}>`, "i").exec(
    stdout,
  );
  return match?.[1];
}

function extractJsonObject(stdout: string) {
  const start = stdout.indexOf("{");
  const end = stdout.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) {
    return undefined;
  }
  return stdout.slice(start, end + 1);
}

function stripJsonFence(content: string) {
  return content
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/```$/i, "")
    .trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatFindings(findings: ReviewFinding[]) {
  if (findings.length === 0) {
    return "No findings.";
  }
  return findings
    .map(
      (finding) =>
        `- ${finding.severity}: ${finding.file ?? "general"}${
          finding.line ? `:${finding.line}` : ""
        } - ${finding.fix}`,
    )
    .join("\n");
}

function formatVerificationSummary(summary: VerificationSummary) {
  const status = summary.passed ? "passed" : "failed";
  const commands = summary.checks
    .map((check) => `- ${check.exitCode === 0 ? "PASS" : "FAIL"}: ${check.command}`)
    .join("\n");
  return `Status: ${status}\n\n${commands}`;
}

function formatVerificationFailure(summary: VerificationSummary) {
  return summary.checks
    .filter((check) => check.exitCode !== 0)
    .map(
      (check) =>
        `${check.command}\nexit ${check.exitCode}\nstdout:\n${tail(
          check.stdout,
          4000,
        )}\nstderr:\n${tail(check.stderr, 4000)}`,
    )
    .join("\n\n");
}

function extractBlockers(body: string) {
  const section = extractMarkdownSection(body, "Blocked by");
  if (section) {
    return issueRefs(section);
  }
  const lineMatch = /^Blocked by:\s*(.+)$/im.exec(body);
  return lineMatch ? issueRefs(lineMatch[1]) : [];
}

function extractMarkdownSection(markdown: string, heading: string) {
  const lines = markdown.split(/\r?\n/);
  const wanted = heading.toLowerCase();
  const collected: string[] = [];
  let inSection = false;

  for (const line of lines) {
    const headingMatch = /^(#{2,6})\s+(.+?)\s*$/.exec(line);
    if (headingMatch) {
      if (inSection) {
        break;
      }
      inSection = headingMatch[2].trim().toLowerCase() === wanted;
      continue;
    }
    if (inSection) {
      collected.push(line);
    }
  }

  return inSection || collected.length > 0 ? collected.join("\n") : undefined;
}

function issueRefs(text: string) {
  const refs = new Set<number>();
  for (const match of text.matchAll(/#(\d+)\b/g)) {
    refs.add(Number(match[1]));
  }
  return [...refs];
}

function issueText(issue: Issue) {
  return `${issueBody(issue)}\n${formatComments(issue)}`;
}

function issueBody(issue: Issue) {
  return issue.body ?? "";
}

function formatComments(issue: Issue) {
  const comments = issue.comments ?? [];
  if (comments.length === 0) {
    return "No comments.";
  }
  return comments
    .map((comment, index) => `Comment ${index + 1}:\n${comment.body ?? ""}`)
    .join("\n\n");
}

function labelSet(issue: Issue) {
  return new Set((issue.labels ?? []).map((label) => label.name));
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
}

function oneLine(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

async function ghJson<T>(args: string[], cwd: string): Promise<T> {
  const result = await runCommand("gh", args, { cwd });
  return JSON.parse(result.stdout) as T;
}

async function commandSucceeds(
  command: string,
  args: string[],
  options: Omit<CommandOptions, "allowFailure"> = {},
) {
  const result = await runCommand(command, args, { ...options, allowFailure: true });
  return result.exitCode === 0;
}

async function runCommand(
  command: string,
  args: string[],
  options: CommandOptions = {},
): Promise<CommandResult> {
  const commandText = formatCommand(command, args);
  const result = await new Promise<CommandResult>((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: { ...process.env, ...options.env },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
      if (options.stream) {
        process.stdout.write(chunk);
      }
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
      if (options.stream) {
        process.stderr.write(chunk);
      }
    });
    child.on("error", reject);
    child.on("close", (exitCode) => {
      resolve({ command: commandText, stdout, stderr, exitCode: exitCode ?? 1 });
    });

    if (options.input !== undefined) {
      child.stdin.end(options.input);
    } else {
      child.stdin.end();
    }
  });

  if (result.exitCode !== 0 && !options.allowFailure) {
    throw new CommandFailed(result);
  }
  return result;
}

function formatCommand(command: string, args: string[]) {
  return [command, ...args].map(shellDisplayQuote).join(" ");
}

function shellDisplayQuote(value: string) {
  if (/^[A-Za-z0-9_./:=@+-]+$/.test(value)) {
    return value;
  }
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

function tail(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }
  return value.slice(value.length - maxLength);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
