import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const dir = dirname(fileURLToPath(import.meta.url));

function loadEmailSubmission() {
  const source = readFileSync(join(dir, "email-submission.ts"), "utf8");
  const compiled = require("typescript").transpileModule(source, {
    compilerOptions: {
      module: require("typescript").ModuleKind.CommonJS,
      target: require("typescript").ScriptTarget.ES2020,
    },
  }).outputText;
  const mockModule = { exports: {} };
  const localRequire = (specifier) => {
    if (specifier === "./lambda-data-client") {
      return { LAMBDA_DATA_AUTH_MODE: "iam", LambdaDataClient: class {} };
    }
    return require(specifier);
  };
  new Function("exports", "require", "module", compiled)(mockModule.exports, localRequire, mockModule);
  return mockModule.exports;
}

function loadEmailMimeIntake(emailSubmission) {
  const source = readFileSync(join(dir, "email-mime-intake.ts"), "utf8");
  const compiled = require("typescript").transpileModule(source, {
    compilerOptions: {
      module: require("typescript").ModuleKind.CommonJS,
      target: require("typescript").ScriptTarget.ES2020,
    },
  }).outputText;
  const mockModule = { exports: {} };
  const localRequire = (specifier) => {
    if (specifier === "./email-submission") {
      return emailSubmission;
    }
    return require(specifier);
  };
  new Function("exports", "require", "module", compiled)(mockModule.exports, localRequire, mockModule);
  return mockModule.exports;
}

const emailSubmission = loadEmailSubmission();
const { parseInboundMimeForIntake } = loadEmailMimeIntake(emailSubmission);

function buildIphonePlainMime() {
  return [
    "Return-Path: <rap@endymion.com>",
    "Content-Type: text/plain; charset=us-ascii",
    "Content-Transfer-Encoding: 7bit",
    "From: Ryan Porter <rap@endymion.com>",
    "Subject: arXiv test",
    "To: submissions@p.apyr.us",
    "",
    "https://arxiv.org/abs/2605.27882",
    "",
    "Sent from my iPhone",
  ].join("\r\n");
}

const intake = parseInboundMimeForIntake(new TextEncoder().encode(buildIphonePlainMime()));
assert.equal(intake.bodyText.includes("arxiv.org/abs/2605.27882"), true, "body must include arXiv URL");
assert.equal(intake.citations.length, 1, "expected one direct citation");
assert.equal(intake.citations[0]?.url, "https://arxiv.org/abs/2605.27882");

console.log("email-mime-intake.test.mjs: ok");
