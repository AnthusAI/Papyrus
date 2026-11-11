import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

/**
 * papyrus-infra backend-deploy: a site's Amplify backend deploy, in place of `npx ampx pipeline-deploy` in the build.
 *
 * The first pass deploys the release at the cost tag wave the stack already has (none, "W/N" or "complete"), so a
 * release's own changes never share a CloudFormation operation with new tags. Then, while the build has time, it adds
 * one wave per pass (amplify/cost-tag-waves.ts), each small enough for CloudFormation's limit, until the root stack output
 * PapyrusCostTagWave says "complete". Waves left over when time runs short are added by the next build, which starts
 * where the stack is, so it never asks for an earlier wave (which would take tags off again). Once complete, a build is
 * one pass, the same deploy as before.
 */

export const COST_TAG_WAVE_VARIABLE = "PAPYRUS_COST_TAG_WAVE";
export const COST_TAG_WAVE_OUTPUT = "PapyrusCostTagWave";
export const COST_TAG_WAVES_COMPLETE = "complete";
/** More passes than any backend needs; a plan that never completes stops here instead of deploying forever. */
export const MAX_PASSES = 12;
/** Amplify's default build timeout, and what the frontend build and the steps around the deploy need after it. */
export const DEFAULT_BUILD_TIMEOUT_MINUTES = 30;
export const RESERVED_MINUTES = 10;

/** Reads "W/N" or "complete" (or nothing) into the wave the deployed stack reached. */
export function parseWaveOutput(value) {
  if (value === undefined || value === null || value === "") return null;
  if (value === COST_TAG_WAVES_COMPLETE) return { complete: true };
  const match = /^([1-9][0-9]*)\/([1-9][0-9]*)$/.exec(value);
  if (!match) throw new Error(`The stack output ${COST_TAG_WAVE_OUTPUT} is ${JSON.stringify(value)}, not "W/N" or "complete".`);
  return { complete: false, wave: Number(match[1]), waves: Number(match[2]) };
}

/** The wave the first pass asks for: the one the stack has. null (no wave variable) for a stack with no cost tags. */
export function firstPassWave(deployed) {
  if (deployed?.complete) return "all";
  return deployed ? String(deployed.wave) : null;
}

/** Minutes this command may spend deploying: the build timeout (_BUILD_TIMEOUT, else 30) less what the rest needs. */
export function deployMinutes(environment = process.env) {
  const timeout = Number(environment._BUILD_TIMEOUT) || DEFAULT_BUILD_TIMEOUT_MINUTES;
  return Math.max(timeout - RESERVED_MINUTES, 0);
}

/**
 * Runs the passes. `deploy(wave)` runs one `ampx pipeline-deploy` with PAPYRUS_COST_TAG_WAVE=wave (unset for null) and
 * throws on failure; `readWave()` reads the deployed root stack's output through parseWaveOutput; `now()` is minutes.
 * A wave pass starts only if the longest pass so far still fits in `minutes`. Returns the waves it deployed.
 */
export function runBackendDeployPasses({ deploy, readWave, minutes = Infinity, now = () => Date.now() / 60000, log = () => {} }) {
  const started = now();
  let wave = firstPassWave(readWave());
  let longest = 0;
  const passes = [];
  for (let pass = 1; pass <= MAX_PASSES; pass += 1) {
    if (pass > 1 && now() - started + longest > minutes) {
      log(`papyrus-infra backend-deploy: stopping before cost tag wave ${wave}, which may not fit in this build; the next build adds it.`);
      return passes;
    }
    log(`papyrus-infra backend-deploy: pass ${pass}, cost tag wave ${wave ?? "none (the release only)"}`);
    const passStarted = now();
    deploy(wave);
    longest = Math.max(longest, now() - passStarted);
    passes.push(wave);
    const reached = readWave();
    if (reached?.complete) return passes;
    if (reached && wave !== null && String(reached.wave) !== wave) throw new Error(`Asked for cost tag wave ${wave} but the stack reports ${reached.wave}/${reached.waves}.`);
    if (!reached && wave !== null) throw new Error(`The deploy left no ${COST_TAG_WAVE_OUTPUT} output on the root stack; is the backend on a Papyrus that tags in waves?`);
    wave = String(reached ? reached.wave + 1 : 1);
  }
  throw new Error(`The cost tags were not complete after ${MAX_PASSES} passes.`);
}

/** The Amplify root stack name for a branch, from the site's own @aws-amplify/platform-core (as ampx names it). */
export function rootStackName({ appId, branch, cwd = process.cwd() }) {
  const require = createRequire(path.join(cwd, "package.json"));
  const { BackendIdentifierConversions } = require("@aws-amplify/platform-core");
  return BackendIdentifierConversions.toStackName({ namespace: appId, name: branch, type: "branch" });
}

function readDeployedWave(stackName, run = spawnSync) {
  const completed = run("aws", ["cloudformation", "describe-stacks", "--stack-name", stackName, "--output", "json"], { encoding: "utf8" });
  if (completed.status !== 0) {
    const message = (completed.stderr || completed.stdout || "").trim();
    if (/does not exist/.test(message)) return null; // a new site: its first deploy starts at wave 1
    throw new Error(`aws cloudformation describe-stacks failed: ${message}`);
  }
  const outputs = JSON.parse(completed.stdout).Stacks?.[0]?.Outputs ?? [];
  return parseWaveOutput(outputs.find((output) => output.OutputKey === COST_TAG_WAVE_OUTPUT)?.OutputValue);
}

function withoutWave(environment) {
  const copy = { ...environment };
  delete copy[COST_TAG_WAVE_VARIABLE];
  return copy;
}

export function runBackendDeployCommand({ environment = process.env, cwd = process.cwd() } = {}) {
  const appId = (environment.AWS_APP_ID ?? "").trim();
  const branch = (environment.AWS_BRANCH ?? "").trim();
  if (!appId || !branch) throw new Error("needs AWS_APP_ID and AWS_BRANCH (it runs inside the Amplify build).");
  const stackName = rootStackName({ appId, branch, cwd });
  return runBackendDeployPasses({
    minutes: deployMinutes(environment),
    readWave: () => readDeployedWave(stackName),
    deploy: (wave) => {
      const completed = spawnSync("npx", ["ampx", "pipeline-deploy", "--branch", branch, "--app-id", appId], {
        cwd,
        stdio: "inherit",
        env: wave === null ? withoutWave(environment) : { ...environment, [COST_TAG_WAVE_VARIABLE]: wave },
      });
      if (completed.status !== 0) throw new Error(`ampx pipeline-deploy (cost tag wave ${wave}) exited with ${completed.status ?? completed.signal}.`);
    },
    log: (line) => console.log(line),
  });
}
