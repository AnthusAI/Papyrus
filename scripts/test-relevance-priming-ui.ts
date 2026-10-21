import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { buildPrimingRequest, DEFAULT_RELEVANCE_CYCLOTRON, isPrimingOutcome, primingRequestPayloadId,
  primingStateText } from "../lib/relevance-status";

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { ReferenceCyclotronPriming } = await import("../components/reference-cyclotron-priming");
  const labels = DEFAULT_RELEVANCE_CYCLOTRON.labels;
  const now = new Date("2026-10-17T12:00:00.000Z");

  assert.equal(primingRequestPayloadId("papyrus-relevance", "Req 1"),
    "knowledge-raw-payload-cyclotron-priming-request-papyrus-relevance-req-1");

  const request = buildPrimingRequest({ url: " https://example.org/a ", label: "exclude", explanation: " Marketing. " },
    "managing-editor", labels, now, "req-1");
  assert.deepEqual(request, {
    requestId: "req-1", url: "https://example.org/a", label: "exclude", explanation: "Marketing.",
    requestedBy: "managing-editor", requestedAt: "2026-10-17T12:00:00.000Z",
  });
  assert.throws(() => buildPrimingRequest({ url: "http://example.org/a", label: "include" }, "x", labels, now), /https/);
  assert.throws(() => buildPrimingRequest({ url: "not a url", label: "include" }, "x", labels, now), /https/);
  assert.throws(() => buildPrimingRequest({ url: "https://example.org/a", label: "maybe" }, "x", labels, now), /include or exclude/);

  assert.ok(isPrimingOutcome({ state: "applied", version: 2, at: "t" }));
  assert.ok(!isPrimingOutcome({ state: "applied" }));
  const waiting = { request, outcome: null };
  const applied = { request, outcome: { state: "applied" as const, version: 2, at: "t" } };
  const failed = { request, outcome: { state: "failed" as const, message: "The page could not be read.", at: "t" } };
  assert.equal(primingStateText(waiting), "Adding");
  assert.equal(primingStateText(applied), "Added");
  assert.equal(primingStateText(failed), "Couldn't add: The page could not be read.");

  const html = renderToStaticMarkup(createElement(ReferenceCyclotronPriming, {
    labels, requests: [waiting, applied, failed], onRequestPriming: () => undefined,
  }));
  for (const text of ["Web page address", "Reference URL", "Include or exclude", ">include</option>",
    ">exclude</option>", "Why (optional)", "Add reference", "Adding",
    "Added", "Couldn&#x27;t add: The page could not be read."]) {
    assert.ok(html.includes(text), `form shows: ${text}`);
  }
  console.log("relevance priming ui: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
