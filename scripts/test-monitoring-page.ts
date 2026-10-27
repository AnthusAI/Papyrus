import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FIXTURE_ALL_PIPELINE_OVERVIEW, FIXTURE_MONITORING_OVERVIEW } from "../lib/monitoring-overview-fixture";
import {
  beginEmailSubmissionAction,
  emailReferenceBatches,
  emailArticleResolutionFailureNotice,
  endEmailSubmissionAction,
  isCurrentEmailSubmissionAction,
} from "../lib/monitoring-overview";
import type { MonitoringResult } from "../lib/monitoring-overview";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

async function main() {
  assert.match(emailArticleResolutionFailureNotice({error: "resolution_failed", reason: "redirect_response_unusable",
    httpStatus: 405, redirectHops: 0}), /HTTP 405; at the tracker/);
  assert.match(emailArticleResolutionFailureNotice({error: "resolution_failed", reason: "redirect_response_unusable",
    httpStatus: 403, redirectHops: 1}), /HTTP 403; after 1 redirect/);
  const unsafeDiagnostic = emailArticleResolutionFailureNotice({error: "resolution_failed",
    reason: "https://private.example/token", httpStatus: 9999, redirectHops: -1});
  assert.ok(!unsafeDiagnostic.includes("private.example") && !unsafeDiagnostic.includes("9999"));

  const newsletterLinks = Array.from({ length: 41 }, (_, index) => `https://example.org/${index}`);
  const linkBatches = emailReferenceBatches(newsletterLinks);
  assert.deepEqual(linkBatches.map((batch) => batch.length), [20, 20, 1],
    "API batches process every selected email link; 20 is not a total selection cap");
  assert.deepEqual(linkBatches.flat(), newsletterLinks);

  // Duplicate actions for one receipt/candidate are suppressed while in flight;
  // another receipt can proceed, and retry is permitted once the first settles.
  const actionLocks = new Set<string>();
  assert.equal(beginEmailSubmissionAction(actionLocks, "resolve:A:0"), true);
  assert.equal(beginEmailSubmissionAction(actionLocks, "resolve:A:0"), false);
  assert.equal(beginEmailSubmissionAction(actionLocks, "resolve:B:0"), true);
  endEmailSubmissionAction(actionLocks, "resolve:A:0");
  assert.equal(beginEmailSubmissionAction(actionLocks, "resolve:A:0"), true);
  endEmailSubmissionAction(actionLocks, "resolve:A:0");

  // Simulate both resolve and import responses arriving after the editor opens B.
  for (const action of ["resolve", "import"]) {
    let activeReceipt: string | null = "A";
    const visibleResults: Record<string, string> = {};
    let finishA!: (value: string) => void;
    let finishB!: (value: string) => void;
    const pendingA = new Promise<string>((resolve) => { finishA = resolve; });
    const pendingB = new Promise<string>((resolve) => { finishB = resolve; });
    const applyWhenCurrent = async (receipt: string, pending: Promise<string>) => {
      const result = await pending;
      if (isCurrentEmailSubmissionAction(activeReceipt, receipt)) visibleResults[receipt] = result;
    };
    const requestA = applyWhenCurrent("A", pendingA);
    activeReceipt = "B";
    const requestB = applyWhenCurrent("B", pendingB);
    finishA(`${action}-A`);
    await requestA;
    assert.deepEqual(visibleResults, {}, `${action} response for a closed receipt is discarded`);
    finishB(`${action}-B`);
    await requestB;
    assert.deepEqual(visibleResults, { B: `${action}-B` }, `${action} response updates only the open receipt`);
  }

  (globalThis as { React?: typeof React }).React = React;
  const { MonitoringOverviewView, EmailSubmissions } = await import("../components/monitoring-overview-view");
  const render = (result: MonitoringResult | null, props: Record<string, unknown> = {}) =>
    renderToStaticMarkup(createElement(MonitoringOverviewView, { result, canViewAll: true, mode: "publication", onModeChange: () => {}, ...props }));

  // A ready overview shows feeds, runs, the queue, relevance with confidence and delivery, and uncapped usage.
  const ready = text(render(FIXTURE_MONITORING_OVERVIEW));
  for (const expected of [
    "Feeds watched", "hn", "news.ycombinator.com", "every 15 min", "Enabled",
    "Recent runs", "2026-10-21 02:33 UTC", "Complete", "Partial", "27 unchanged",
    "Router", "Live", "Feedback on",
    "Usage", "Observed router decisions", "Decisions today (2026-10-21)", "2", "Decisions in inspected history", "3",
    "Collected queue", "Fresh Show HN", "Collected, waiting for the router", "Routed", "Error", "invalid request: bad title",
    "Quantum paper on arXiv", "Relevant", "91% confidence", "In the References queue",
    "Phishing kit leaks", "Not in the References queue: delivery failed",
    "1 item judged not relevant to this publication is not listed",
  ]) assert.ok(ready.includes(expected), `ready view shows: ${expected}`);
  assert.ok(!ready.includes(" of 100") && !ready.includes(" of 300"), "usage is not presented against an arbitrary ceiling");

  // The delivered item links to its References entry on the viewing publication; the failed one does not.
  const html = render(FIXTURE_MONITORING_OVERVIEW);
  assert.match(html, /href="\/newsroom\/references\/lin-1"/);
  assert.ok(!html.includes("references/lin-3"));

  // The default view names only the viewing publication.
  assert.ok(!ready.includes("desk-b") && !ready.includes("desk-c"));

  // Status is words and marks, not colour alone.
  assert.match(html, /data-delivery="delivered"/);
  assert.match(html, /data-routing="error"/);

  // Whole-pipeline mode lists every publication; other publications' references are not linked from this site.
  const all = render(FIXTURE_ALL_PIPELINE_OVERVIEW, { mode: "all" });
  const allText = text(all);
  for (const expected of ["desk-a", "desk-b", "Not relevant", "desk-c", "confidence not reported"]) {
    assert.ok(allText.includes(expected), `whole pipeline shows: ${expected}`);
  }
  assert.ok(!all.includes("references/lin-2"), "a reference in another publication's queue is not linked from this site");

  const withEmail = {
    ...FIXTURE_MONITORING_OVERVIEW,
    emailSubmissions: [{ receiptId: `EMAIL#${"a".repeat(64)}`, observedAt: "2026-10-21T02:30:00Z", status: "pending_review",
      subject: "Newsletter", envelopeSender: "sender@example.net", headerFrom: "forged@example.net",
      warnings: ["ses_authentication_unverified"], verdicts: { spf: "FAIL", dkim: "PASS", dmarc: "FAIL", spam: "PASS", virus: "PASS" },
      linkCount: 2, processedCount: 0, unresolvedLinkCount: 1, reviewRequired: true, errorCode: null }],
  };
  const emailDetail = { submission: { ...withEmail.emailSubmissions[0], corpusId: "corpus-1" },
    safeBodyText: "Hello <script>never execute</script>\nhttps://example.org/story",
    candidateLinks: [{ url: "https://link.mail.beehiiv.com/ss/c/opaque", title: "Tracked story",
      resolutionStatus: "unresolved" as const }], sourceMaterialIsUntrusted: true as const };
  const single = renderToStaticMarkup(createElement(EmailSubmissions, { items: [emailDetail.submission], detail: emailDetail,
    onResolveArticleLink: async () => ({ error: "resolution_failed" as const }),
    onImportCandidates: async () => ({ imported: 0, references: [] }),
  }));
  assert.ok(single.includes("Add selected links to References") && single.includes("Resolve article redirect"));
  assert.ok(!single.includes("Read email and review candidate links") && !single.includes("Feeds watched"));
  const emailHtml = render(withEmail, { emailDetail });
  const emailText = text(emailHtml);
  for (const expected of ["Email submissions", "Newsletter", "MIME From (unverified)", "SPF FAIL", "Tracked story", "private review required", "Sender and message content are untrusted"]) {
    assert.ok(emailText.includes(expected), `email view shows: ${expected}`);
  }
  assert.ok(emailHtml.includes("&lt;script&gt;never execute"), "original HTML is escaped as inert text");
  assert.ok(!emailHtml.includes("<script>") && !emailHtml.includes("tracker.example"),
    "rendering never activates markup or remote images");
  assert.ok(emailText.includes("tracking redirect not opened") && !emailHtml.includes('href="https://link.mail.beehiiv.com/'),
    "recipient tracking URLs remain visible as non-clickable text");
  assert.ok(emailText.includes("Add selected links to References") && emailText.includes("Add as pending Reference"),
    "email candidates have an explicit path into the existing pending Reference queue");
  assert.ok(emailText.includes("does not approve, label, classify, or publish"),
    "email import is separate from editorial decisions and publication");
  assert.match(emailHtml, /Add selected links to References[^<]*<\/button>/);
  assert.match(emailHtml, /disabled=""[^>]*>Add selected links to References/,
    "preview/demo rendering cannot invoke live intake without editor actions");

  const importReadyDetail = { ...emailDetail,
    candidateLinks: [{ url: "https://example.org/story", title: "Story" }] };
  const importReadyHtml = render(withEmail, { emailDetail: importReadyDetail,
    onImportCandidates: async () => ({ imported: 1, references: [{ id: "ref-1", sourceUri: "https://example.org/story", title: "Story", curationStatus: "pending" }] }),
  });
  assert.match(importReadyHtml, /Add selected links to References/);

  // Only admins are offered the whole-pipeline switch.
  assert.ok(text(render(FIXTURE_MONITORING_OVERVIEW)).includes("Whole shared pipeline"));
  assert.ok(!text(render(FIXTURE_MONITORING_OVERVIEW, { canViewAll: false })).includes("Whole shared pipeline"));

  // Permission denied, empty, unconfigured, unavailable and loading each say so plainly.
  assert.ok(text(render({ error: "forbidden" })).includes("Monitoring is for editors and admins"));
  assert.ok(!render({ error: "forbidden" }).includes("Feeds watched"), "a refused request shows no data");
  const empty = text(render({ ...FIXTURE_MONITORING_OVERVIEW, state: "empty", feeds: [], runs: [], routerRuns: [], router: null, usage: null, items: [], hiddenNotRelevant: 0 }));
  assert.ok(empty.includes("Nothing has been collected yet"));
  assert.ok(text(render({ state: "not_configured" })).includes("Monitoring is not set up for this publication"));
  assert.ok(text(render({ state: "unavailable" })).includes("Monitoring could not be read right now"));
  assert.ok(text(render(null)).includes("Loading monitoring"));

  // Ready, but nothing queued or run yet.
  const quiet = text(render({ ...FIXTURE_MONITORING_OVERVIEW, runs: [], routerRuns: [], items: [], hiddenNotRelevant: 0, usage: { day: "2026-10-21", decisionsToday: 0, decisionsTotal: 0, historyComplete: true } }));
  assert.ok(quiet.includes("No collector runs recorded yet") && quiet.includes("No items in the queue"));
  const partialUsage = text(render({ ...FIXTURE_MONITORING_OVERVIEW, usage: { ...FIXTURE_MONITORING_OVERVIEW.usage!, historyComplete: false } }));
  assert.ok(partialUsage.includes("At least 2") && partialUsage.includes("At least 3") && partialUsage.includes("bounded history read"));

  // A publication outside the router says so instead of showing others' decisions.
  const unrouted = text(render({ ...FIXTURE_MONITORING_OVERVIEW, notice: "publication_not_routed", scope: { mode: "publication", publicationId: null, site: null, canViewAll: false }, items: FIXTURE_MONITORING_OVERVIEW.items.map((i) => ({ ...i, relevance: [] })) }));
  assert.ok(unrouted.includes("This publication is not one of the router's outputs"));

  console.log("monitoring page: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
