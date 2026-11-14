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

function buildMultipartMime() {
  const boundary = "outer-boundary";
  const inner = "inner-boundary";
  return [
    "From: Editor <editor@example.org>",
    "Subject: Newsletter",
    `Content-Type: multipart/mixed; boundary="${boundary}"`,
    "",
    "This is a multi-part message in MIME format.",
    `--${boundary}`,
    `Content-Type: multipart/alternative; boundary=${inner}`,
    "",
    `--${inner}`,
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: quoted-printable",
    "",
    "Read this: https://example.org/story=3Fid=3D7",
    `--${inner}`,
    "Content-Type: text/html; charset=utf-8",
    "Content-Transfer-Encoding: base64",
    "",
    Buffer.from('<p><a href="https://example.org/other">other</a></p>').toString("base64"),
    `--${inner}--`,
    `--${boundary}`,
    "Content-Type: application/pdf",
    "Content-Disposition: attachment; filename=paper.pdf",
    "",
    "https://example.org/inside-the-attachment",
    `--${boundary}--`,
    "",
  ].join("\r\n");
}

const multipart = parseInboundMimeForIntake(new TextEncoder().encode(buildMultipartMime()));
assert.equal(multipart.subject, "Newsletter");
assert.equal(multipart.bodyText, "Read this: https://example.org/story?id=7");
assert.deepEqual(multipart.citations.map((entry) => entry.url), ["https://example.org/story?id=7", "https://example.org/other"]);

const htmlOnly = parseInboundMimeForIntake(new TextEncoder().encode([
  "Subject: Html only",
  "Content-Type: text/html; charset=utf-8",
  "",
  '<p>See <a href="https://example.org/a">this</a></p>',
].join("\r\n")));
assert.equal(htmlOnly.bodyText, "See this");
assert.deepEqual(htmlOnly.citations.map((entry) => entry.url), ["https://example.org/a"]);

// A message with no readable text has no body and no links: nothing is read out of the raw bytes.
const empty = parseInboundMimeForIntake(new TextEncoder().encode(["Subject: Nothing", "Content-Type: application/pdf", "", "https://example.org/in-a-pdf"].join("\r\n")));
assert.equal(empty.bodyText, "");
assert.equal(empty.citations.length, 0);

console.log("email-mime-intake.test.mjs: multipart ok");
