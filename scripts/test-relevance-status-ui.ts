import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { buildReviewRateRequest, cyclotronStatusPayloadId, DEMO_CYCLOTRON_STATUS, latestCyclotronStatus,
  reviewRateRequestPayloadId } from "../lib/relevance-status";

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { ReferenceCyclotronStatus } = await import("../components/reference-cyclotron-status");

  // The browser and the sweep name the same records.
  assert.equal(cyclotronStatusPayloadId("papyrus-relevance"), "knowledge-raw-payload-cyclotron-status-papyrus-relevance");
  assert.equal(reviewRateRequestPayloadId("Papyrus Relevance"), "knowledge-raw-payload-cyclotron-review-rate-request-papyrus-relevance");

  // The newest valid snapshot wins; other JSON is ignored.
  const older = { ...DEMO_CYCLOTRON_STATUS, asOf: "2026-05-15T00:00:00.000Z" };
  assert.equal(latestCyclotronStatus([
    { json: older, updatedAt: "2026-05-15T00:00:00Z" },
    { json: DEMO_CYCLOTRON_STATUS, updatedAt: "2026-05-16T12:00:00Z" },
    { json: { schema: "something-else" }, updatedAt: "2026-05-17T00:00:00Z" },
  ]), DEMO_CYCLOTRON_STATUS);

  // A request says who asked, for how long; clearing is its own request.
  const now = new Date("2026-10-09T12:00:00.000Z");
  assert.deepEqual(buildReviewRateRequest({ rate: 0.5, days: 7 }, "managing-editor", now), {
    rate: 0.5, expiresAt: "2026-10-16T12:00:00.000Z", setBy: "managing-editor", requestedAt: "2026-10-09T12:00:00.000Z",
  });
  assert.deepEqual(buildReviewRateRequest({ clear: true }, "managing-editor", now),
    { clear: true, setBy: "managing-editor", requestedAt: "2026-10-09T12:00:00.000Z" });
  assert.throws(() => buildReviewRateRequest({ rate: 1.5, days: 7 }, "x", now), /between/);

  // The strip renders in words; a stale snapshot says how old it is.
  const strip = renderToStaticMarkup(createElement(ReferenceCyclotronStatus, {
    status: DEMO_CYCLOTRON_STATUS, now: new Date("2026-05-18T12:00:00.000Z"),
  }));
  for (const text of ["Version 1", "Agreement not measured yet", "Onboarding · 100% reviewed", "1 awaiting review",
    "Snapshot from 48 hours ago", "What the cyclotron is doing"]) {
    assert.ok(strip.includes(text), `strip shows: ${text}`);
  }
  console.log("relevance status ui: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
