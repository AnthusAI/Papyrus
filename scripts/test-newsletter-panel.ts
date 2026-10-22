import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { newsletterOperationDocument, NEWSLETTER_MUTATION_OPERATIONS, NEWSLETTER_QUERY_OPERATIONS } from "../lib/newsletter-client";
import { createFixtureApi, FIXTURE_TIME_ZONE, fixtureIssues } from "../lib/newsletter-fixture";
import {
  canApprove, canCancel, canStop, countsText, failureText, formatInZone, isoToZonedInput, nextWholeHourInput, statusLabel, subscribersToCsv,
  validTimeZone, zonedInputToIso, type NewsletterOverview,
} from "../lib/newsletter-model";
import { NEWSLETTER_OPERATION_GROUPS } from "../amplify/plugins/newsletter/schema";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");

async function main() {
  (globalThis as { React?: typeof React }).React = React;

  // The client calls exactly the operations the schema defines, as queries or mutations to match.
  const operations = [...NEWSLETTER_QUERY_OPERATIONS, ...NEWSLETTER_MUTATION_OPERATIONS].sort();
  assert.deepEqual(operations, Object.keys(NEWSLETTER_OPERATION_GROUPS).sort());
  assert.equal(newsletterOperationDocument("newsletterOverview"), "query NewsletterOverview($input: AWSJSON) { newsletterOverview(input: $input) }");
  assert.equal(newsletterOperationDocument("newsletterErase"), "mutation NewsletterErase($input: AWSJSON) { newsletterErase(input: $input) }");

  // Statuses: known words, unknown ones shown as written (an alert kind may add its own), approval rules.
  assert.equal(statusLabel("awaiting_approval"), "Awaiting approval");
  assert.equal(statusLabel("quarantined"), "Quarantined");
  assert.equal(statusLabel("needs_legal_review"), "Needs legal review");
  assert.ok(canApprove("draft") && canApprove("awaiting_approval") && canApprove("scheduled") && canApprove("blocked"));
  assert.ok(!canApprove("sending") && !canApprove("sent") && !canApprove("stopped") && !canApprove("cancelled") && !canApprove("quarantined"));
  assert.ok(canCancel("scheduled") && !canCancel("draft") && canStop("sending") && !canStop("sent"));

  // Times: next whole hour and conversion in the site zone, across a clock change.
  assert.equal(validTimeZone("Not/AZone"), null);
  assert.equal(nextWholeHourInput(new Date("2027-01-15T14:20:00Z"), FIXTURE_TIME_ZONE), "2027-01-15T10:00");
  assert.equal(nextWholeHourInput(new Date("2027-01-15T14:00:00Z"), FIXTURE_TIME_ZONE), "2027-01-15T10:00");
  assert.equal(nextWholeHourInput(new Date("2027-01-16T04:30:00Z"), FIXTURE_TIME_ZONE), "2027-01-16T00:00");
  assert.equal(nextWholeHourInput(new Date("2027-01-15T14:20:00Z"), "Asia/Kolkata"), "2027-01-15T20:00");
  assert.equal(zonedInputToIso("2027-01-15T09:00", FIXTURE_TIME_ZONE), "2027-01-15T14:00:00Z");
  assert.equal(zonedInputToIso("2027-07-15T09:00", FIXTURE_TIME_ZONE), "2027-07-15T13:00:00Z");
  assert.equal(zonedInputToIso("2027-03-14T09:00", FIXTURE_TIME_ZONE), "2027-03-14T13:00:00Z", "the day after clocks go forward");
  assert.equal(zonedInputToIso("2027-01-15T09:00", "Asia/Kolkata"), "2027-01-15T03:30:00Z");
  assert.equal(zonedInputToIso("nonsense", "UTC"), null);
  assert.equal(isoToZonedInput("2027-01-15T14:00:00Z", FIXTURE_TIME_ZONE), "2027-01-15T09:00");
  assert.equal(formatInZone("2027-01-15T14:00:00Z", FIXTURE_TIME_ZONE), "2027-01-15 09:00 EST");
  assert.equal(formatInZone(undefined, "UTC"), "not set");
  for (const local of ["2027-01-15T09:00", "2027-11-07T09:30", "2027-06-01T23:45"]) {
    assert.equal(isoToZonedInput(zonedInputToIso(local, FIXTURE_TIME_ZONE) as string, FIXTURE_TIME_ZONE), local, `round trip ${local}`);
  }

  // Counts read in plain words and leave out zeroes.
  assert.equal(countsText({}), "nothing sent yet");
  assert.equal(countsText({ queued: 5, sent: 4, delivered: 3, bounced: 1, failed: 0, softBounced: 2 }), "5 queued, 4 sent, 3 delivered, 1 bounced, 2 soft bounced");

  // Failures: the postal address is an operator task and the panel says where it is set; others use plain words.
  assert.match(failureText({ ok: false, error: "postal_address_missing" }), /operator sets it in the site's AWS configuration/);
  assert.equal(failureText({ ok: false, error: "forbidden" }), "Your role cannot do this.");
  assert.equal(failureText({ ok: false, error: "something_new", message: "A new thing" }), "A new thing");

  // The CSV neutralises formulas in addresses and wording, quotes commas and keeps the header.
  const csv = subscribersToCsv([
    { email: "=cmd@example.com", status: "confirmed", lists: "weekly:subscribed", createdAt: "2027-01-01T00:00:00Z", consentRequestedAt: "", consentConfirmedAt: "", consentFormId: "newsletter", consentPageUrl: "https://news.example.com/", consentWording: "Yes, \"send\" it" },
  ]);
  assert.equal(csv.split("\r\n")[0], "email,status,lists,createdAt,consentRequestedAt,consentConfirmedAt,consentFormId,consentPageUrl,consentWording");
  assert.ok(csv.includes("'=cmd@example.com,") && csv.includes('"Yes, ""send"" it"'));
  assert.equal(subscribersToCsv([]), "email,status,lists,createdAt,consentRequestedAt,consentConfirmedAt,consentFormId,consentPageUrl,consentWording\r\n");

  // The fixture service answers like the functions: admin-only operations refuse an editor, deliveries mask addresses, approve moves state.
  const admin = createFixtureApi({ admin: true });
  const editor = createFixtureApi({ admin: false });
  for (const operation of ["newsletterSubscribers", "newsletterExport", "newsletterErase", "newsletterResume", "newsletterApproveIssue", "newsletterCancelIssue", "newsletterStopIssue"] as const) {
    assert.deepEqual(await editor(operation, { issueId: "a1" }), { ok: false, error: "forbidden" }, `${operation} refuses an editor`);
  }
  const masked = JSON.stringify(await editor("newsletterIssueDeliveries", { issueId: "a6" }));
  assert.ok(masked.includes("r***@example.com") && !masked.includes("reader1@example.com"));
  assert.ok(JSON.stringify(await admin("newsletterIssueDeliveries", { issueId: "a6" })).includes("reader1@example.com"));
  const approved = (await admin("newsletterApproveIssue", { issueId: "a1", sendAt: "2027-01-22T14:00:00Z" })) as { ok: boolean; issue: { status: string; sendAt: string } };
  assert.deepEqual([approved.ok, approved.issue.status, approved.issue.sendAt], [true, "scheduled", "2027-01-22T14:00:00Z"]);
  assert.equal(((await admin("newsletterApproveIssue", { issueId: "a6", sendAt: "2027-01-22T14:00:00Z" })) as { error: string }).error, "invalid_state");

  // Sections render from fixtures.
  const { ListsCard, SiteStatusCard, IssueSummary, DeliveriesCard, SubscribersTable } = await import("../components/newsletter-sections");
  const overview = (await admin("newsletterOverview")) as unknown as NewsletterOverview;
  const lists = text(renderToStaticMarkup(createElement(ListsCard, { overview })));
  for (const expected of ["Weekly roundup (roundup)", "412", "17 pending", "38 unsubscribed", "Security alerts (alerts)", "488 confirmed", "12 addresses are suppressed"]) {
    assert.ok(lists.includes(expected), `lists show: ${expected}`);
  }
  const paused = renderToStaticMarkup(createElement(SiteStatusCard, { paused: overview.paused, isAdmin: true, busy: false, onResume: () => {} }));
  assert.ok(text(paused).includes("Sending is paused") && paused.includes("data-newsletter-resume"));
  assert.ok(!renderToStaticMarkup(createElement(SiteStatusCard, { paused: overview.paused, isAdmin: false, busy: false, onResume: () => {} })).includes("data-newsletter-resume"), "editors get no Resume button");
  assert.ok(text(renderToStaticMarkup(createElement(SiteStatusCard, { paused: { paused: false }, isAdmin: true, busy: false, onResume: () => {} }))).includes("Sending is on"));

  const issues = fixtureIssues();
  const row = (id: string, extra: Record<string, unknown> = {}) =>
    renderToStaticMarkup(createElement(IssueSummary, { issue: { ...issues.find((issue) => issue.issueId === id)!, ...extra }, zone: FIXTURE_TIME_ZONE, demo: false }));
  const scheduled = row("a3");
  assert.match(scheduled, /<time dateTime="2027-01-15T14:00:00Z" title="2027-01-15 14:00 UTC">2027-01-15 09:00 EST<\/time>/, "site time with UTC on hover");
  assert.ok(text(scheduled).includes("Edited since approval"));
  assert.match(scheduled, /href="\/newsroom\/articles\/item-weekly-0115"/);
  assert.ok(text(row("a4")).includes("Blocked: postal address missing"));
  assert.ok(text(row("a6")).includes("418 sent, 409 delivered, 3 bounced, 1 complained, 1 failed, 2 suppressed, 2 soft bounced"));
  assert.match(row("a6"), /href="https:\/\/news.example.com\/roundup\/2026-12-25.html"[^>]*rel="noreferrer noopener"/);
  assert.ok(text(row("a2")).includes("Awaiting approval") && text(row("a7")).includes("Quarantined"), "unknown statuses render");
  assert.match(row("a6"), /data-newsletter-status="sent"/);
  assert.ok(row("a6").includes("✓") && row("a4").includes("!"), "status has a mark as well as a word");

  const deliveries = ((await admin("newsletterIssueDeliveries", { issueId: "a6" })) as { deliveries: never[] }).deliveries;
  const history = text(renderToStaticMarkup(createElement(DeliveriesCard, { issue: issues[5], rows: deliveries, events: overview.events.filter((event) => event.issue === "a6"), hasMore: true, loading: false, isAdmin: true, onMore: () => {} })));
  for (const expected of ["reader3@example.com", "bounced", "complained", "failed (MessageRejected)", "(erased)", "Recent events for this issue", "Bounce (Permanent)", "Load more deliveries"]) {
    assert.ok(history.includes(expected), `delivery history shows: ${expected}`);
  }
  assert.ok(text(renderToStaticMarkup(createElement(DeliveriesCard, { issue: issues[5], rows: [], events: [], hasMore: false, loading: false, isAdmin: false, onMore: () => {} }))).includes("Addresses are masked for editors"));

  const table = text(renderToStaticMarkup(createElement(SubscribersTable, { rows: ((await admin("newsletterSubscribers", {})) as { subscribers: never[] }).subscribers, zone: FIXTURE_TIME_ZONE })));
  assert.ok(table.includes("reader1@example.com") && table.includes("weekly (subscribed), alerts-security (subscribed)") && table.includes("not yet"));

  // The panel itself, before anything has loaded, is a status line and nothing else: no addresses without an answer.
  (globalThis as { React?: typeof React }).React = React;
  const { NewsletterPanel } = await import("../components/newsletter-panel");
  const first = renderToStaticMarkup(createElement(NewsletterPanel, { isAdmin: true, isDemo: true }));
  assert.ok(first.includes('data-news-desk-admin-panel="newsletter"') && first.includes("Loading") && !first.includes("@example.com"));

  console.log("newsletter panel ok");
}

void main();
