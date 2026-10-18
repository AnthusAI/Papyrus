import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parsePrimingProofReport, primingProofHeadline } from "../lib/priming-proof-report";

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { PrimingProofPage } = await import("../components/priming-proof-page");
  const pythonReport = JSON.parse(readFileSync(new URL("./fixtures/synthetic-priming-proof-report.json", import.meta.url), "utf-8"));

  const report = parsePrimingProofReport(pythonReport);
  const headline = primingProofHeadline(report);
  assert.equal(headline.baseline.agreement, 0.5);
  assert.equal(headline.latest.labels, 6);
  assert.equal(headline.agreementChangeInPoints, 50);

  assert.throws(() => parsePrimingProofReport({ ...pythonReport, points: pythonReport.points.slice(1) }), /zero-label baseline/);
  assert.throws(() => parsePrimingProofReport({ ...pythonReport, version: "cyclotron-priming-proof/v0" }));

  const published = renderToStaticMarkup(createElement(PrimingProofPage, { report }));
  assert.match(published, /data-priming-proof="published"/);
  assert.match(published, /<strong>50%<\/strong> with no labels to\s*<strong>100%<\/strong> after 6 labels \(\+50 points\)/);
  assert.equal((published.match(/data-priming-proof-point=/g) ?? []).length, 3);
  assert.match(published, /1 include, 5 exclude/);

  assert.match(published, /A classifier that always gives the same answer agrees on half of it/);

  const crossValidatedReport = parsePrimingProofReport({
    ...pythonReport,
    heldOut: { ...pythonReport.heldOut, design: "5-fold cross-validation: every reviewed Reference is held out exactly once" },
  });
  const crossValidated = renderToStaticMarkup(createElement(PrimingProofPage, { report: crossValidatedReport }));
  assert.match(crossValidated, /5-fold cross-validation: every reviewed Reference is held out exactly once/);
  assert.doesNotMatch(crossValidated, /agrees on half of it/);

  const pending = renderToStaticMarkup(createElement(PrimingProofPage, { report: null }));
  assert.match(pending, /data-priming-proof="pending"/);
  assert.match(pending, /No approved proof run/);
  console.log("priming proof page: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
