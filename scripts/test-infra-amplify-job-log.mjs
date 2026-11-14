#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { findFirstErrorLine, tailLines } from "../packages/papyrus/src/amplify-job-log.mjs";

const execFileAsync = promisify(execFile);
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cli = path.join(repo, "packages/papyrus/bin/papyrus-infra.mjs");
const fixtures = path.join(repo, "features_backend/fixtures/amplify-job-log");

assert.deepEqual(findFirstErrorLine("fine\nall good\nFATAL ERROR: boom\nError: later"), { lineNumber: 3, text: "FATAL ERROR: boom" });
assert.equal(findFirstErrorLine("fine\nall good"), null);
const withPipNoise = "[WARNING]: ERROR: pip's dependency resolver does not currently take into account all the packages\n[WARNING]: FATAL ERROR: Ineffective mark-compacts near heap limit - JavaScript heap out of memory\n[ERROR]: !!! Build failed";
assert.equal(findFirstErrorLine(withPipNoise).lineNumber, 2);
assert.equal(findFirstErrorLine("a\nsome Error happened").lineNumber, 2);
const numbered = Array.from({ length: 500 }, (_, index) => `line ${index + 1}`).join("\n");
assert.equal(tailLines(numbered).length, 200);
assert.equal(tailLines(numbered)[199], "line 500");
assert.equal(tailLines("a\nb").length, 2);

const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-infra-job-log-"));
const binDirectory = path.join(work, "bin");
fs.mkdirSync(binDirectory);
fs.copyFileSync(path.join(fixtures, "fake-aws.mjs"), path.join(binDirectory, "aws"));
fs.chmodSync(path.join(binDirectory, "aws"), 0o755);

let servedLog = "";
const server = http.createServer((_request, response) => response.end(servedLog));
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const logUrl = `http://127.0.0.1:${server.address().port}/build.log`;

async function runNode(commandArguments, environment = process.env) {
  try {
    const { stdout, stderr } = await execFileAsync("node", commandArguments, { encoding: "utf8", env: environment });
    return { status: 0, stdout, stderr };
  } catch (error) {
    return { status: error.code ?? 1, stdout: error.stdout ?? "", stderr: error.stderr ?? "" };
  }
}

function runJobLog(scenarioName, extraArguments) {
  const scenarioFile = path.join(fixtures, `${scenarioName}.json`);
  servedLog = JSON.parse(fs.readFileSync(scenarioFile, "utf8")).log;
  return runNode([cli, "amplify", "job-log", "--app-id", "dexample0001", ...extraArguments], {
    ...process.env, PATH: `${binDirectory}:${process.env.PATH}`, FAKE_AWS_SCENARIO: scenarioFile, FAKE_LOG_URL: logUrl,
  });
}

try {
  const unknownPlugin = await runJobLog("unknown-plugin", ["--latest-failed"]);
  assert.equal(unknownPlugin.status, 0, unknownPlugin.stderr);
  assert.match(unknownPlugin.stdout, /Amplify job 42 on app dexample0001 branch main: FAILED/);
  assert.match(unknownPlugin.stdout, /BUILD\s+FAILED/);
  assert.match(unknownPlugin.stdout, /DEPLOY\s+CANCELLED/);
  assert.match(unknownPlugin.stdout, /BUILD log, last 200 lines/);
  assert.match(unknownPlugin.stdout, /Cause: ReprojectOnDeploy CREATE_FAILED: .*Unknown plugin 'home-page'/);
  assert.match(unknownPlugin.stdout, /First error in the BUILD log \(line 7\): \[ERROR\]: \[BackendBuildError\]/);
  assert.doesNotMatch(unknownPlugin.stdout, /stale failure from a previous job/);

  const heap = await runJobLog("heap-out-of-memory", ["--job", "42"]);
  assert.equal(heap.status, 0, heap.stderr);
  assert.match(heap.stdout, /Cause: BUILD log line 8: FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory/);

  const missingModule = await runJobLog("missing-cli-login", ["--latest-failed", "--branch", "main"]);
  assert.equal(missingModule.status, 0, missingModule.stderr);
  assert.match(missingModule.stdout, /Cause: BUILD log line 8: ModuleNotFoundError: No module named 'cli_login'/);

  const missingAppId = await runNode([cli, "amplify", "job-log"]);
  assert.notEqual(missingAppId.status, 0);
  assert.match(missingAppId.stderr, /--app-id is required/);

  const unknownSubcommand = await runNode([cli, "amplify", "nope"]);
  assert.notEqual(unknownSubcommand.status, 0);
  assert.match(unknownSubcommand.stderr, /amplify job-log/);
} finally {
  server.close();
  fs.rmSync(work, { recursive: true, force: true });
}
console.log("amplify job-log: ok");
