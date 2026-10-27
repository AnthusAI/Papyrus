import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FIXTURE_ALL_PIPELINE_OVERVIEW, FIXTURE_MONITORING_OVERVIEW } from "../lib/monitoring-overview-fixture";
import {
  beginEmailSubmissionAction,
  emailReferenceBatches,
  endEmailSubmissionAction,
  formatUtc,
  isCurrentEmailSubmissionAction,
} from "../lib/monitoring-overview";
import { mergeListPages, withLoadedPages } from "../lib/monitoring-paging";
import type { MonitoringEmailSummary } from "../lib/monitoring-overview";
import type { MonitoringResult } from "../lib/monitoring-overview";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

async function main() {
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
      linkCount: 2, processedCount: 0, unresolvedLinkCount: 1, reviewRequired: true, errorCode: null,
      quarantine: { state: "released" as const, failure: null,
        decision: { action: "accept" as const, by: "editor@example.test", at: "2026-10-21T03:00:00Z", reason: "Known sender" } } }],
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

  // Several copies of the same email are one item: "received N times", the dates, and one decision for all.
  const copyDates = ["2026-10-27T01:00:00Z", "2026-10-27T01:05:00Z", "2026-10-27T01:09:00Z"];
  const grouped = { ...emailDetail.submission, status: "pending_review",
    quarantine: { state: "quarantined" as const, decision: null, failure: null },
    group: { fingerprint: "f".repeat(64), count: 3, copies: copyDates.map((observedAt, index) => ({
      receiptId: `EMAIL#${String(index).repeat(64)}`, observedAt, status: "pending_review", linkCount: 41, processedCount: 0,
      quarantine: { state: "quarantined" as const, decision: null, failure: null } })) } };
  const groupedHtml = renderToStaticMarkup(createElement(EmailSubmissions, { items: [grouped],
    detail: { ...emailDetail, submission: grouped }, onDecide: async () => ({ error: "bad_request" as const }) }));
  const groupedText = text(groupedHtml);
  assert.ok(groupedText.includes("Received 3 times"), "a repeated email shows how many times it was received");
  assert.equal((groupedHtml.match(/data-email-copy=/g) ?? []).length, 3, "expanding lists every copy");
  assert.ok(copyDates.every((date) => groupedHtml.includes(formatUtc(date))), "every copy shows its date");
  assert.ok(groupedText.includes("One decision applies to all 3 copies of this email."), "Accept/Reject covers the group");
  assert.equal((groupedHtml.match(/data-email-decision="accept"/g) ?? []).length, 1, "one Accept for the group");
  const single_ = renderToStaticMarkup(createElement(EmailSubmissions, { items: [{ ...grouped, group: undefined }] }));
  assert.ok(!single_.includes("Received") && !single_.includes("data-email-group"), "a single email shows no group");

  // A held message is read-only text until an editor accepts it; Accept and Reject are buttons with Lucide icons.
  const held = { ...emailDetail.submission, status: "pending_review",
    quarantine: { state: "quarantined" as const, decision: null, failure: null } };
  const heldDetail = { ...emailDetail, submission: held,
    candidateLinks: [{ url: "https://example.org/story", title: "Story" }, { url: "https://link.mail.beehiiv.com/ss/c/opaque", title: "Tracked", resolutionStatus: "unresolved" as const }] };
  const decisions: unknown[][] = [];
  const heldHtml = renderToStaticMarkup(createElement(EmailSubmissions, { items: [held], detail: heldDetail,
    onDecide: async (...args: unknown[]) => { decisions.push(args); return { error: "bad_request" as const }; },
    onImportCandidates: async () => ({ imported: 0, references: [] }), onResolveArticleLink: async () => ({ error: "resolution_failed" as const }) }));
  const heldText = text(heldHtml);
  for (const expected of ["Held for review", "Accept", "Reject", "Why? (optional)", "stay inert text"]) {
    assert.ok(heldText.includes(expected), `held message shows: ${expected}`);
  }
  assert.match(heldHtml, /data-email-decision="accept"[^>]*>.*?lucide-check/s, "Accept carries a Lucide check icon");
  assert.match(heldHtml, /data-email-decision="reject"[^>]*>.*?lucide-x/s, "Reject carries a Lucide x icon");
  assert.match(heldHtml, /<textarea[^>]*maxLength="500"/, "the reason is a textarea");
  assert.ok(!heldHtml.includes("<select") && !heldHtml.includes("✓") && !heldHtml.includes("✗"), "buttons and Lucide icons only");
  assert.ok(!heldText.includes("Add selected links to References") && !heldHtml.includes("Resolve article redirect") &&
    !heldHtml.includes('href="https://example.org/story"') && !heldHtml.includes('type="checkbox"'),
    "nothing can be imported, resolved or opened from a held message");
  assert.ok(!/disabled=""[^>]*data-email-decision/.test(heldHtml), "decision buttons are enabled for an editor session");
  const noHandler = renderToStaticMarkup(createElement(EmailSubmissions, { items: [held], detail: heldDetail }));
  assert.match(noHandler, /disabled=""[^>]*data-email-decision="accept"|data-email-decision="accept"[^>]*disabled=""/, "preview/demo cannot decide");
  for (const [state, shown] of [["release_requested", "Accepted, being queued"], ["discard_requested", "Rejected, being closed"],
    ["discarded", "Rejected"], ["expired", "can no longer be accepted"], ["decision_failed", "could not be applied"]] as const) {
    const html = renderToStaticMarkup(createElement(EmailSubmissions, { items: [{ ...held, quarantine: { state, failure: state === "decision_failed" ? "email_retry_binding_changed" : null,
      decision: { action: state.startsWith("release") ? "accept" as const : "reject" as const, by: "ed@example.test", at: "2026-10-21T03:00:00Z", reason: "Because" } } }],
      detail: { ...heldDetail, submission: { ...held, quarantine: { state, failure: state === "decision_failed" ? "email_retry_binding_changed" : null,
        decision: { action: state.startsWith("release") ? "accept" as const : "reject" as const, by: "ed@example.test", at: "2026-10-21T03:00:00Z", reason: "Because" } } } } }));
    assert.ok(text(html).includes(shown), `${state} shows: ${shown}`);
    assert.ok(!html.includes("data-email-decision=\"accept\""), `${state} offers no further decision`);
    assert.ok(text(html).includes("by ed@example.test") || state === "expired", `${state} records who decided`);
  }
  const acceptedHtml = renderToStaticMarkup(createElement(EmailSubmissions, { items: [emailDetail.submission], detail: emailDetail,
    onImportCandidates: async () => ({ imported: 0, references: [] }) }));
  assert.ok(text(acceptedHtml).includes("Accepted by editor@example.test") && text(acceptedHtml).includes("Why: Known sender"));

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

  // Monitors not routed to this site are named in a collapsed note, never listed with items.
  const othersHtml = render({ ...FIXTURE_MONITORING_OVERVIEW, otherMonitors: ["hn", "huggingface"] });
  assert.ok(text(othersHtml).includes("Not routed to this site (2)"));
  assert.ok(othersHtml.includes('data-monitoring-other-monitor="hn"') && othersHtml.includes("<details") && !othersHtml.includes("<details open"));
  assert.ok(!text(render(FIXTURE_MONITORING_OVERVIEW)).includes("Not routed to this site"));

  // Paging: the newest page shows "Load more" only while a list has a cursor; there is no total.
  const email = (n: number, held = false): MonitoringEmailSummary => ({
    receiptId: `EMAIL#${n}`, observedAt: `2026-10-20T00:${String(n % 60).padStart(2, "0")}:00Z`, status: held ? "pending_review" : "queued",
    subject: `Mail ${n}`, envelopeSender: null, headerFrom: null, warnings: [], verdicts: {}, linkCount: 1, processedCount: 0,
    unresolvedLinkCount: 0, reviewRequired: held, errorCode: null,
    quarantine: held ? { state: "quarantined", decision: null, failure: null } : null,
  });
  const base = { ...FIXTURE_MONITORING_OVERVIEW, emailSubmissions: Array.from({ length: 20 }, (_, i) => email(44 - i)),
    cursors: { emailSubmissions: "next-email", runs: null, items: null, routerRuns: null } };
  const withMore = render(base, { paging: { onLoadMore: () => {}, loadingList: null, onHeldOnlyChange: () => {} } });
  assert.ok(withMore.includes('data-monitoring-load-more="emailSubmissions"'), "a list with a cursor offers Load more");
  assert.ok(!withMore.includes('data-monitoring-load-more="runs"') && !withMore.includes('data-monitoring-load-more="items"'),
    "a list that has ended offers no Load more");
  assert.ok(text(withMore).includes("Held for review") && text(withMore).includes("Load more"));
  assert.ok(!render({ ...base, cursors: {} }, { paging: { onLoadMore: () => {} } }).includes("data-monitoring-load-more"),
    "no cursor, no button");
  assert.ok(!render(base).includes("data-monitoring-load-more"), "the demo has no paging");
  assert.ok(render(base, { paging: { onLoadMore: () => {}, loadingList: "emailSubmissions" } }).includes("disabled"), "the button waits while loading");
  const heldEmpty = text(render({ ...base, emailSubmissions: [], cursors: {} }, { paging: { heldOnly: true, onHeldOnlyChange: () => {} } }));
  assert.ok(heldEmpty.includes("No email submissions are held for review."));
  const heldFilterHtml = render(base, { paging: { heldOnly: true, onHeldOnlyChange: () => {} } });
  assert.ok(/data-email-filter="held"[^>]*>/.test(heldFilterHtml) && /aria-pressed="true"[^>]*data-email-filter="held"/.test(heldFilterHtml), "Held for review shows as pressed");

  // Loaded pages follow the refreshed newest page without duplicating a row that moved between them.
  const merged = mergeListPages("emailSubmissions", [email(46), email(45), email(44)], [email(45), email(44), email(43)]);
  assert.deepEqual(merged.map((row) => row.subject), ["Mail 46", "Mail 45", "Mail 44", "Mail 43"]);
  const item = (revision: number) => ({ ...FIXTURE_MONITORING_OVERVIEW.items[0], monitorId: "hn", sourceId: "7", revision });
  assert.deepEqual(mergeListPages("items", [item(1)], [item(2)]).map((row) => row.revision), [2], "the highest revision of an item wins");
  const shown = withLoadedPages(base, { emailSubmissions: { rows: [email(24), email(23)], cursor: null } }, null);
  assert.equal(shown.emailSubmissions!.length, 22);
  assert.equal(shown.cursors!.emailSubmissions, null, "the last loaded page ends the list");
  assert.equal(shown.cursors!.runs, null);
  const heldOnly = withLoadedPages(base, {}, { rows: [email(3, true)], cursor: "older-held" });
  assert.deepEqual(heldOnly.emailSubmissions!.map((row) => row.subject), ["Mail 3"], "the held filter replaces the email list");
  assert.equal(heldOnly.cursors!.emailSubmissions, "older-held");

  console.log("monitoring page: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
