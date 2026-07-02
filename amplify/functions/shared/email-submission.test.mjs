import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const dir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(dir, "email-submission.ts"), "utf8");
const compiled = require("typescript").transpileModule(source, {
  compilerOptions: { module: require("typescript").ModuleKind.CommonJS, target: require("typescript").ScriptTarget.ES2020 },
}).outputText;
const mockModule = { exports: {} };
const localRequire = (specifier) => {
  if (specifier === "./lambda-data-client") {
    return { LAMBDA_DATA_AUTH_MODE: "iam", LambdaDataClient: class {} };
  }
  return require(specifier);
};
new Function("exports", "require", "module", compiled)(mockModule.exports, localRequire, mockModule);
const {
  parseInboundEmailBody,
  countInboundAttachments,
  classifyNewSubmissionIntake,
  extractDirectCitations,
} = mockModule.exports;

function buildPdfOnlyMime() {
  const boundary = "----PapyrusPdfUnitTest";
  const pdf = `%PDF-1.4\nDOI: 10.5555/papyrus.pdf.unit.test\n%%EOF\n`;
  return [
    `From: tester@example.com`,
    `To: submissions@p.apyr.us`,
    `Subject: PDF only`,
    `MIME-Version: 1.0`,
    `Content-Type: multipart/mixed; boundary="${boundary}"`,
    ``,
    `--${boundary}`,
    `Content-Type: text/plain`,
    ``,
    ``,
    `--${boundary}`,
    `Content-Type: application/pdf`,
    `Content-Disposition: attachment; filename="paper.pdf"`,
    ``,
    pdf,
    `--${boundary}--`,
    ``,
  ].join("\r\n");
}

const pdfOnlyBytes = new TextEncoder().encode(buildPdfOnlyMime());
const parsed = parseInboundEmailBody(pdfOnlyBytes);
assert.equal(parsed.text, "", "empty text/plain must not fall back to PDF bytes");
assert.equal(extractDirectCitations(parsed.text).length, 0);
assert.equal(countInboundAttachments(pdfOnlyBytes), 1);
assert.equal(
  classifyNewSubmissionIntake(parsed.text, [], countInboundAttachments(pdfOnlyBytes)),
  "pdf_only_intake",
);

console.log("email-submission.test.mjs: ok");
