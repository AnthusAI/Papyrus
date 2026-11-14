import { spawnSync } from "node:child_process";

const LOG_TAIL_LINE_COUNT = 200;
const STRONG_ERROR_PATTERN = /FATAL|\[ERROR\]|BackendBuildError|Unknown plugin|No module named|heap out of memory|Build timed out/;
const GENERIC_ERROR_PATTERN = /\bError\b|\bERROR\b/;
const BENIGN_NOISE_PATTERN = /dependency resolver does not currently take into account/;
const BUILD_STEP_NAME = "BUILD";
const CASCADED_FAILURE_PATTERN = /cancell?ed|Resource creation cancelled|did not stabilize after another resource failed/i;

export function runAwsJson(awsArguments) {
  const completed = spawnSync("aws", [...awsArguments, "--output", "json"], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
  if (completed.status !== 0) {
    throw new Error(`aws ${awsArguments.slice(0, 2).join(" ")} failed: ${(completed.stderr || completed.stdout).trim()}`);
  }
  return completed.stdout.trim() === "" ? {} : JSON.parse(completed.stdout);
}

export async function downloadText(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`log download failed with HTTP ${response.status}`);
  return response.text();
}

export function findFirstErrorLine(logText) {
  const lines = logText.split("\n");
  const candidateLines = lines.map((line, position) => ({ line, position })).filter(({ line }) => !BENIGN_NOISE_PATTERN.test(line));
  const strong = candidateLines.find(({ line }) => STRONG_ERROR_PATTERN.test(line));
  const found = strong ?? candidateLines.find(({ line }) => GENERIC_ERROR_PATTERN.test(line));
  const index = found ? found.position : -1;
  return index < 0 ? null : { lineNumber: index + 1, text: lines[index].trim() };
}

export function tailLines(logText, lineCount = LOG_TAIL_LINE_COUNT) {
  const lines = logText.replace(/\n+$/, "").split("\n");
  return lines.slice(Math.max(0, lines.length - lineCount));
}

function findJobSummary({ appId, branch, jobId, latestFailed, regionArguments, runAws }) {
  if (jobId) return { jobId };
  let nextToken;
  do {
    const tokenArguments = nextToken ? ["--next-token", nextToken] : [];
    const page = runAws(["amplify", "list-jobs", "--app-id", appId, "--branch-name", branch, ...regionArguments, ...tokenArguments]);
    const summaries = page.jobSummaries ?? [];
    const match = latestFailed ? summaries.find((summary) => summary.status === "FAILED") : summaries[0];
    if (match) return match;
    nextToken = page.nextToken;
  } while (nextToken);
  throw new Error(latestFailed ? `no failed job found for app ${appId} branch ${branch}` : `no jobs found for app ${appId} branch ${branch}`);
}

function findRootStackName({ appId, branch, regionArguments, runAws }) {
  const stacks = runAws(["cloudformation", "describe-stacks", ...regionArguments]).Stacks ?? [];
  const root = stacks.find((stack) => stack.StackName.startsWith(`amplify-${appId}-${branch}-branch`) && !stack.ParentId);
  return root ? root.StackName : null;
}

export function collectStackFailures({ stackName, notBefore, regionArguments, runAws, visited = new Set() }) {
  if (visited.has(stackName)) return [];
  visited.add(stackName);
  const events = runAws(["cloudformation", "describe-stack-events", "--stack-name", stackName, ...regionArguments]).StackEvents ?? [];
  const failedEvents = events
    .filter((event) => /FAILED/.test(event.ResourceStatus ?? ""))
    .filter((event) => notBefore === null || Date.parse(event.Timestamp) >= notBefore)
    .sort((left, right) => Date.parse(left.Timestamp) - Date.parse(right.Timestamp));
  const failures = [];
  for (const event of failedEvents) {
    failures.push({ stackName, timestamp: event.Timestamp, logicalId: event.LogicalResourceId, resourceType: event.ResourceType, status: event.ResourceStatus, reason: event.ResourceStatusReason ?? "" });
    const isNestedStack = event.ResourceType === "AWS::CloudFormation::Stack" && (event.PhysicalResourceId ?? "").startsWith("arn:");
    if (isNestedStack && event.PhysicalResourceId !== stackName) {
      failures.push(...collectStackFailures({ stackName: event.PhysicalResourceId, notBefore, regionArguments, runAws, visited }));
    }
  }
  return failures;
}

function rootCauseOf(failures) {
  const candidates = failures.filter((failure) => failure.reason && !CASCADED_FAILURE_PATTERN.test(failure.reason));
  return candidates.length === 0 ? null : [...candidates].sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))[0];
}

export async function buildJobLogReport({ appId, branch = "main", jobId, latestFailed = false, region }, { runAws = runAwsJson, download = downloadText } = {}) {
  const regionArguments = region ? ["--region", region] : [];
  const summary = findJobSummary({ appId, branch, jobId, latestFailed, regionArguments, runAws });
  const job = runAws(["amplify", "get-job", "--app-id", appId, "--branch-name", branch, "--job-id", summary.jobId, ...regionArguments]).job;
  const jobSummary = job.summary ?? {};
  const steps = job.steps ?? [];
  const out = [];
  out.push(`Amplify job ${jobSummary.jobId ?? summary.jobId} on app ${appId} branch ${branch}: ${jobSummary.status ?? "unknown"}`);
  if (jobSummary.commitMessage) out.push(`Commit: ${jobSummary.commitMessage.split("\n")[0]}`);
  if (jobSummary.startTime) out.push(`Started: ${jobSummary.startTime}   Ended: ${jobSummary.endTime ?? "not ended"}`);
  out.push("", "Steps:");
  for (const step of steps) out.push(`  ${step.stepName.padEnd(12)} ${step.status}`);

  const failedSteps = steps.filter((step) => step.status === "FAILED");
  const stepsToShow = failedSteps.length > 0 ? failedSteps : steps.filter((step) => step.stepName === BUILD_STEP_NAME);
  let firstError = null;
  let buildLogText = "";
  for (const step of stepsToShow) {
    if (!step.logUrl) {
      out.push("", `${step.stepName} log: no log URL`);
      continue;
    }
    let logText;
    try {
      logText = await download(step.logUrl);
    } catch (error) {
      out.push("", `${step.stepName} log: could not be downloaded (${error instanceof Error ? error.message : error})`);
      continue;
    }
    if (step.stepName === BUILD_STEP_NAME) buildLogText = logText;
    const found = findFirstErrorLine(logText);
    if (found && !firstError) firstError = { ...found, stepName: step.stepName };
    out.push("", `${step.stepName} log, last ${LOG_TAIL_LINE_COUNT} lines:`, ...tailLines(logText).map((line) => `  ${line}`));
  }

  const rootStackName = findRootStackName({ appId, branch, regionArguments, runAws });
  const startTime = jobSummary.startTime ? Date.parse(jobSummary.startTime) : null;
  const failures = rootStackName ? collectStackFailures({ stackName: rootStackName, notBefore: Number.isNaN(startTime) ? null : startTime, regionArguments, runAws }) : [];
  out.push("", rootStackName ? `CloudFormation stack ${rootStackName}: ${failures.length} failed event(s) since the job started` : "CloudFormation stack: none found for this app and branch");
  for (const failure of failures) out.push(`  ${failure.timestamp} ${failure.logicalId} (${failure.resourceType}) ${failure.status}: ${failure.reason}`);

  const stackCause = rootCauseOf(failures);
  out.push("");
  if (buildLogText.includes("Build timed out")) {
    out.push("Cause: the build timed out. Check the stack above before any retry: a retry is only for an environment failure, and only once.");
  } else if (stackCause) {
    out.push(`Cause: ${stackCause.logicalId} ${stackCause.status}: ${stackCause.reason}`);
  } else if (firstError) {
    out.push(`Cause: ${firstError.stepName} log line ${firstError.lineNumber}: ${firstError.text}`);
  } else {
    out.push("Cause: no error line found in the log or the stack events; read the log tail above.");
  }
  if (stackCause && firstError) out.push(`First error in the ${firstError.stepName} log (line ${firstError.lineNumber}): ${firstError.text}`);
  return `${out.join("\n")}\n`;
}

export async function runAmplifyJobLogCommand(optionOf, hasFlag) {
  const appId = optionOf("app-id");
  if (!appId) throw new Error("--app-id is required");
  const report = await buildJobLogReport({
    appId,
    branch: optionOf("branch", "main"),
    jobId: optionOf("job"),
    latestFailed: hasFlag("latest-failed"),
    region: optionOf("region", process.env.AWS_REGION),
  });
  process.stdout.write(report);
}
