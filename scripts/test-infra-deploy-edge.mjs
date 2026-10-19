#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cli = path.join(repo, "packages/papyrus/bin/papyrus-infra.mjs");
const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-infra-edge-"));

const fakeAwsSource = `#!/usr/bin/env node
const fs = require("node:fs");
const argumentsList = process.argv.slice(2);
fs.appendFileSync(process.env.FAKE_AWS_LOG, argumentsList.join(" ") + "\\n");
const joined = argumentsList.join(" ");
if (joined.startsWith("cloudformation list-stack-resources")) {
  const present = (process.env.FAKE_AWS_PRESENT_LOGICAL_IDS || "").split(",").filter(Boolean);
  process.stdout.write(JSON.stringify({ StackResourceSummaries: present.map((id) => ({ LogicalResourceId: id })) }));
} else if (joined.startsWith("cloudformation wait change-set-create-complete")) {
  process.exit(process.env.FAKE_AWS_NO_CHANGES ? 255 : 0);
} else if (joined.startsWith("cloudformation describe-change-set")) {
  process.stdout.write(JSON.stringify(process.env.FAKE_AWS_NO_CHANGES
    ? { Status: "FAILED", StatusReason: "The submitted information didn't contain changes." }
    : { Status: "CREATE_COMPLETE", Changes: [{ ResourceChange: { Action: "Modify", LogicalResourceId: "ReaderEdgeFunction" } }] }));
} else if (joined.startsWith("cloudfront describe-function")) {
  process.stdout.write(JSON.stringify({ ETag: "ETAGVALUE" }));
}
`;

try {
  const binDirectory = path.join(work, "bin");
  fs.mkdirSync(binDirectory);
  fs.writeFileSync(path.join(binDirectory, "aws"), fakeAwsSource, { mode: 0o755 });
  const adoptionTemplate = path.join(work, "adoption.yaml");
  const finalTemplate = path.join(work, "final.yaml");
  const templateText = "AWSTemplateFormatVersion: x\nParameters:\n  CertificateArn:\n    Type: String\n  ReaderCertificateArn:\n    Type: String\nResources:\n  A:\n    Type: X\n";
  fs.writeFileSync(adoptionTemplate, templateText);
  fs.writeFileSync(finalTemplate, templateText);
  const adoptResources = path.join(work, "adopt.json");
  fs.writeFileSync(adoptResources, JSON.stringify([
    { ResourceType: "AWS::CloudFront::Function", LogicalResourceId: "ReaderEdgeFunction", ResourceIdentifier: { FunctionName: "papyrus-reader-edge" } },
  ]));

  function runEdgeDeploy(extraEnvironment) {
    const log = path.join(work, `log-${Math.random()}.txt`);
    const environment = { ...process.env, PATH: `${binDirectory}:${process.env.PATH}`, FAKE_AWS_LOG: log, AWS_APP_ID: "dapp", AWS_BRANCH: "main", ...extraEnvironment };
    const stdout = execFileSync("node", [cli, "deploy-edge", "--stack", "papyrus-edge-p-apyr-us", "--template", finalTemplate, "--adoption-template", adoptionTemplate, "--adopt-resources", adoptResources, "--parameter", "ReaderCertificateArn=arn:reader", "--delete-function", "papyrus-legacy-reader-redirect", "--only-app-id", "dapp"], { encoding: "utf8", env: environment });
    return { stdout, calls: fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "" };
  }

  const adopting = runEdgeDeploy({});
  assert.match(adopting.calls, /create-change-set .*--change-set-type IMPORT .*--resources-to-import/);
  assert.match(adopting.calls, /wait stack-import-complete/);
  assert.match(adopting.calls, /create-change-set .*--change-set-type UPDATE/);
  assert.match(adopting.calls, /ParameterKey=CertificateArn,UsePreviousValue=true/);
  assert.match(adopting.calls, /ParameterKey=ReaderCertificateArn,ParameterValue=arn:reader/);
  assert.match(adopting.calls, /cloudfront delete-function --name papyrus-legacy-reader-redirect --if-match ETAGVALUE/);

  const alreadyAdopted = runEdgeDeploy({ FAKE_AWS_PRESENT_LOGICAL_IDS: "ReaderEdgeFunction", FAKE_AWS_NO_CHANGES: "1" });
  assert.equal(alreadyAdopted.calls.includes("IMPORT"), false, "adoption is skipped once the resources are in the stack");
  assert.equal(alreadyAdopted.calls.includes("execute-change-set"), false, "an empty change set is never executed");
  assert.match(alreadyAdopted.stdout, /has no changes/);

  const outsideBuild = execFileSync("node", [cli, "deploy-edge", "--stack", "s", "--template", finalTemplate], { encoding: "utf8", env: { ...process.env, AWS_APP_ID: "", AWS_BRANCH: "" } });
  assert.match(outsideBuild, /not running inside an Amplify build, skipping/);
  const otherApp = runEdgeDeploy({ AWS_APP_ID: "dother" });
  assert.match(otherApp.stdout, /does not own the stack, skipping/);

  console.log("infra deploy-edge tests passed");
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
