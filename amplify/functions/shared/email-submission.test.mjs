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
  readInboundSenderAuthenticationFromSesReceipt,
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

const sesPassHeaders = [
  "Authentication-Results: amazonses.com;",
  " spf=pass (spfCheck: domain of example.com designates 1.2.3.4 as permitted sender) client-ip=1.2.3.4;",
  " dkim=pass header.i=@example.com;",
  " dmarc=pass header.from=example.com;",
];
const passing = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders([...sesPassHeaders, "From: a@example.com", "Subject: x"]),
);
assert.deepEqual(passing, { spf: "pass", dkim: "pass" });
assert.equal(isInboundSenderAuthenticated(passing), true);

const spfOnly = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders(["Authentication-Results: amazonses.com; spf=pass; dkim=none;", "From: a@example.com"]),
);
assert.equal(isInboundSenderAuthenticated(spfOnly), true);

const dkimOnly = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders(["Authentication-Results: amazonses.com; spf=fail; dkim=pass;", "From: a@example.com"]),
);
assert.equal(isInboundSenderAuthenticated(dkimOnly), true);

const bothFail = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders(["Authentication-Results: amazonses.com; spf=fail; dkim=fail;", "From: a@example.com"]),
);
assert.equal(isInboundSenderAuthenticated(bothFail), false);

const noHeader = readInboundSenderAuthenticationFromRawMime(mimeWithHeaders(["From: a@example.com"]));
assert.equal(isInboundSenderAuthenticated(noHeader), false);

const forgedLowerHeader = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders([
    "Authentication-Results: amazonses.com; spf=fail; dkim=fail;",
    "From: a@example.com",
    "Authentication-Results: amazonses.com; spf=pass; dkim=pass;",
  ]),
);
assert.equal(isInboundSenderAuthenticated(forgedLowerHeader), false, "only the topmost header counts");

const forgedByUntrustedServer = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders(["Authentication-Results: evil.example; spf=pass; dkim=pass;", "From: a@example.com"]),
);
assert.equal(isInboundSenderAuthenticated(forgedByUntrustedServer), false);

const forgedInBody = readInboundSenderAuthenticationFromRawMime(
  mimeWithHeaders(["From: a@example.com"], "Authentication-Results: amazonses.com; spf=pass; dkim=pass;"),
);
assert.equal(isInboundSenderAuthenticated(forgedInBody), false);

assert.deepEqual(
  readInboundSenderAuthenticationFromSesReceipt({ spfVerdict: { status: "PASS" }, dkimVerdict: { status: "FAIL" } }),
  { spf: "pass", dkim: "fail" },
);
assert.equal(readInboundSenderAuthenticationFromSesReceipt({}), null);

console.log("email-submission.test.mjs: ok");
