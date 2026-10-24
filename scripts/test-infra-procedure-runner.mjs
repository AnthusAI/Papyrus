#!/usr/bin/env node
// The procedure runner's role grants what story-state triggers use (docs/automations.md, "Deployment needs").
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const template = fs.readFileSync(path.join(repo, "infra/procedures/papyrus-procedure-runner.yaml"), "utf8");

function statement(sid) {
  const start = template.indexOf(`- Sid: ${sid}\n`);
  assert.notEqual(start, -1, `statement ${sid} exists`);
  const rest = template.slice(start + 1);
  const next = rest.search(/\n\s+- Sid: |\n\s{2}\w+:\n/);
  return next === -1 ? rest : rest.slice(0, next);
}

const rows = statement("StageTriggerRows");
for (const action of ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]) assert.match(rows, new RegExp(action));
assert.match(rows, /dynamodb:LeadingKeys: \["MONITOR#\*"\]/);
assert.doesNotMatch(rows, /DeleteItem|Scan/);

const invoke = statement("StartNextStage");
assert.match(invoke, /lambda:InvokeFunction/);
assert.match(invoke, /function:papyrus-procedure-runner"/);
assert.doesNotMatch(invoke, /function:\*/);

assert.match(statement("TriggerOutcomes"), /dynamodb:UpdateItem/);
console.log("procedure runner template: ok");
