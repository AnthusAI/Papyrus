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
  isInboundSenderAuthenticated,
  readInboundSenderAuthenticationFromRawMime,
  readInboundScanVerdictsFromSesReceipt,
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

function mimeWithHeaders(headerLines, body = "hello") {
  return new TextEncoder().encode([...headerLines, "", body].join("\r\n"));
}

function authenticated(headerLines, fromAddress = "a@example.com") {
  return isInboundSenderAuthenticated(
    readInboundSenderAuthenticationFromRawMime(mimeWithHeaders(headerLines)),
    fromAddress,
  );
}

const sesPassHeaders = [
  "X-SES-Spam-Verdict: PASS",
  "X-SES-Virus-Verdict: PASS",
  "Authentication-Results: amazonses.com;",
  " spf=pass (spfCheck: domain of example.com designates 1.2.3.4 as permitted sender) client-ip=1.2.3.4;",
  " envelope-from=a@example.com;",
  " helo=mail.example.com;",
  " dkim=pass header.i=@example.com;",
  " dmarc=pass header.from=example.com;",
  "From: a@example.com",
];
assert.equal(authenticated(sesPassHeaders), true);
assert.equal(authenticated(sesPassHeaders, "Alice <a@mail.example.com>"), true, "subdomain alignment");

assert.equal(authenticated([
  "Authentication-Results: amazonses.com; spf=pass; envelope-from=a@example.com; dkim=none;",
]), true);
assert.equal(authenticated([
  "Authentication-Results: amazonses.com; spf=fail; envelope-from=a@example.com; dkim=pass header.d=example.com;",
]), true);
assert.equal(authenticated([
  "Authentication-Results: amazonses.com; spf=fail; dkim=fail;",
]), false);

assert.equal(authenticated([
  "Authentication-Results: amazonses.com; spf=pass; envelope-from=attacker@evil.test; dkim=pass header.i=@evil.test;",
]), false, "passing SPF/DKIM for another domain must not authenticate a spoofed From");
assert.equal(authenticated([
  "Authentication-Results: amazonses.com; spf=pass; envelope-from=a@notexample.com;",
]), false, "suffix lookalike domain must not align");

assert.equal(authenticated(["From: a@example.com"]), false);
assert.equal(authenticated([
  "Authentication-Results: amazonses.com; spf=fail; dkim=fail;",
  "Authentication-Results: amazonses.com; spf=pass; envelope-from=a@example.com;",
]), false, "only the topmost header counts");
assert.equal(authenticated([
  "Authentication-Results: evil.example; spf=pass; envelope-from=a@example.com; dkim=pass header.i=@example.com;",
]), false);
assert.equal(isInboundSenderAuthenticated(
  readInboundSenderAuthenticationFromRawMime(
    mimeWithHeaders(["From: a@example.com"], "Authentication-Results: amazonses.com; spf=pass; envelope-from=a@example.com;"),
  ),
  "a@example.com",
), false, "headers in the body are ignored");

assert.equal(authenticated(["X-SES-Spam-Verdict: FAIL", ...sesPassHeaders.slice(1)]), false);
assert.equal(authenticated(["X-SES-Virus-Verdict: FAIL", ...sesPassHeaders]), false, "first verdict header wins, forged later PASS cannot hide FAIL");
assert.equal(authenticated([sesPassHeaders[0], "X-SES-Virus-Verdict: FAIL", ...sesPassHeaders.slice(2)]), false);

assert.deepEqual(
  readInboundScanVerdictsFromSesReceipt({ spamVerdict: { status: "FAIL" }, virusVerdict: { status: "PASS" } }),
  { spamVerdict: "fail", virusVerdict: "pass" },
);

console.log("email-submission.test.mjs: ok");
