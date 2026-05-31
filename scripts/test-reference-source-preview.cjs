#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

registerTypeScriptRequire();

const {
  isCitationLandingPageUrl,
  isDirectPdfUrl,
  pickPdfAttachmentHref,
  resolveReferenceSourcePreview,
} = require("../lib/reference-source-preview.ts");
const { parseReferenceLineageIdFromNewsroomPathname } = require("../lib/newsroom-index-filters.ts");

assert.equal(isCitationLandingPageUrl("https://arxiv.org/abs/2308.10792"), true);
assert.equal(isDirectPdfUrl("https://example.com/paper.pdf"), true);
assert.equal(isDirectPdfUrl("https://arxiv.org/abs/2308.10792"), false);

const pdfAttachment = {
  id: "att-1",
  referenceId: "ref-1",
  referenceLineageId: "ref-1",
  referenceVersionKey: "v1",
  role: "source",
  sortKey: "0",
  storagePath: "corpora/AI-ML-research/agentbench-evaluating-llms-as-agents.pdf",
  sourceUri: "https://arxiv.org/abs/2308.10792",
  filename: "agentbench-evaluating-llms-as-agents.pdf",
  mediaType: "application/pdf",
};

assert.equal(
  pickPdfAttachmentHref(pdfAttachment, pdfAttachment.sourceUri),
  null,
  "landing page alone should not be used as PDF href",
);

const signedUrl = "https://bucket.s3.amazonaws.com/corpora/AI-ML-research/agentbench.pdf?X-Amz-Signature=abc";
assert.equal(
  pickPdfAttachmentHref({ ...pdfAttachment, sourceUri: signedUrl }, pdfAttachment.sourceUri),
  signedUrl,
);

const preview = resolveReferenceSourcePreview(pdfAttachment.sourceUri, [
  { ...pdfAttachment, sourceUri: signedUrl },
]);
assert.equal(preview?.kind, "pdf");
assert.equal(preview?.href, signedUrl);
assert.equal(preview?.embedUrl, signedUrl);

assert.equal(
  parseReferenceLineageIdFromNewsroomPathname(
    "/newsroom/references/reference-knowledge-corpus-ai-ml-research-a47f3f11-18cb-4aa1-b69d-44c38026bfeb",
  ),
  "reference-knowledge-corpus-ai-ml-research-a47f3f11-18cb-4aa1-b69d-44c38026bfeb",
);
assert.equal(parseReferenceLineageIdFromNewsroomPathname("/newsroom/references"), null);

console.log("test-reference-source-preview: ok");

function registerTypeScriptRequire() {
  if (require.extensions[".ts"]) return;
  require.extensions[".ts"] = (module, filename) => {
    const source = fs.readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        moduleResolution: ts.ModuleResolutionKind.Node10,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    });
    module._compile(output.outputText, filename);
  };
}
