import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  buildActionLog,
  buildHidden,
  buildQueue,
  moderationModeText,
  parseSignals,
  receiptMessage,
  safeHttpUrl,
  shortReader,
  type ActionRow,
  type CommentRow,
  type ReportRow,
  type SubmissionRow,
} from "../lib/reader-moderation";

const READER = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-000000000002";
const handles = { [READER]: "quiet-fox" };

const submission = (id: string, changes: Partial<SubmissionRow> = {}): SubmissionRow => ({
  id: `sub-${id.padStart(24, "0")}`, canonicalUrl: "https://example.com/post", domain: "example.com", title: "A small tool", readerId: READER, state: "pending",
  moderation: "new", createdAt: `2026-10-22T0${id}:00:00.000Z`, ...changes,
});
const comment = (id: string, changes: Partial<CommentRow> = {}): CommentRow => ({
  id: `cmt-${id.padStart(32, "0")}`, subjectKey: "item-one", readerId: READER, body: "Worth reading.", state: "visible", moderation: "new", createdAt: `2026-10-22T0${id}:30:00.000Z`, ...changes,
});
const report = (target: string, changes: Partial<ReportRow> = {}): ReportRow => ({
  id: `rep-${target}`, targetType: "comment", target, reporterReaderId: OTHER, reason: "An advert", state: "open", createdAt: "2026-10-22T09:00:00.000Z", ...changes,
});

test("the queue holds new and reported items, newest first, with reports and signals attached", () => {
  const reported = comment("3", { moderation: "new" });
  const queue = buildQueue({
    submissions: [submission("1"), submission("2", { moderation: "approved" })],
    comments: [comment("2"), reported, comment("4", { state: "deleted", body: "" }), comment("5", { moderation: "approved" })],
    reports: [report(reported.id), report(reported.id, { id: "rep-closed", state: "closed" })],
    handles,
  });
  assert.deepEqual(queue.map((row) => row.id), [reported.id, comment("2").id, submission("1").id], "newest first; reviewed and deleted items stay out");
  const row = queue[0];
  assert.deepEqual([row.kind, row.handle, row.reports.length, row.reports[0].reason], ["comment", "quiet-fox", 1, "An advert"], "only open reports");
  assert.equal(queue[2].canPromote, true);
  assert.equal(queue[1].canPromote, false);
});

test("the hidden list holds hidden submissions and comments, including ones a pre-moderation hold keeps back", () => {
  const hidden = buildHidden({ submissions: [submission("1", { state: "hidden" }), submission("2")], comments: [comment("3", { state: "hidden", moderation: "approved" })], reports: [], handles });
  assert.deepEqual(hidden.map((row) => row.kind), ["comment", "submission"]);
  assert.equal(hidden[1].canPromote, false, "a hidden submission cannot be promoted until it is shown again");
});

test("signals are parsed from the JSON string, worst first, and never throw", () => {
  const signals = parseSignals(JSON.stringify([{ source: "humanus", policy: "shouting", detector: "capitals", severity: "info", excerpt: "BUY" }, { source: "humanus", policy: "chatbot-artifacts", detector: "hope-this-helps", severity: "error", excerpt: "I hope this helps" }]));
  assert.deepEqual(signals.map((signal) => signal.severity), ["error", "info"]);
  for (const bad of [undefined, null, "", "not json", "{}", 7, [1, "x"], "[null]"]) assert.deepEqual(parseSignals(bad), [], String(bad));
});

test("only http and https addresses become links", () => {
  assert.equal(safeHttpUrl("https://example.com/a"), "https://example.com/a");
  for (const unsafe of ["javascript:alert(1)", "data:text/html,x", "ftp://example.com/", "//example.com", "", null, undefined, "not a url"]) assert.equal(safeHttpUrl(unsafe), null, String(unsafe));
  const row = buildQueue({ submissions: [submission("1", { canonicalUrl: "javascript:alert(1)" })], comments: [], reports: [], handles })[0];
  assert.equal(row.url, null);
});

test("the log is newest first; any action can be undone once except a promotion", () => {
  const action = (id: string, changes: Partial<ActionRow>): ActionRow => ({ id: `mod-${id.padStart(32, "0")}`, by: "human", actorSub: "staff", action: "hide", targetType: "submission", target: submission("1").id, fromState: "pending", toState: "hidden", at: `2026-10-22T0${id}:00:00.000Z`, ...changes });
  const log = buildActionLog([action("1", {}), action("2", { action: "promote" }), action("3", { undoneBy: "mod-x" }), action("4", { by: "ai", action: "ban", targetType: "reader" })]);
  assert.deepEqual(log.map((entry) => [entry.label, entry.undoable, entry.byLabel]), [["Banned", true, "AI moderator"], ["Hidden", false, "A moderator"], ["Promoted to a draft", false, "A moderator"], ["Hidden", true, "A moderator"]]);
  assert.equal(buildActionLog(Array.from({ length: 80 }, (_, number) => action(String(number % 9), { id: `mod-${String(number).padStart(32, "0")}` }))).length, 50);
});

test("words for the receipt, the mode and a reader", () => {
  assert.equal(receiptMessage({ status: "ok", id: "mod-1" }), "Done.");
  assert.equal(receiptMessage({ status: "refused", error: "target_changed", message: "That item changed while you were looking at it." }), "That item changed while you were looking at it.");
  assert.equal(receiptMessage({ status: "refused" }), "The action was refused.");
  assert.match(receiptMessage(null), /did not answer/);
  assert.match(moderationModeText("off"), /Moderation is off/);
  assert.match(moderationModeText("human"), /wait here for a decision/);
  assert.equal(shortReader(READER, "quiet-fox"), "quiet-fox (00000000)");
  assert.equal(shortReader(READER, null), "reader 00000000");
});

async function view() {
  (globalThis as { React?: typeof React }).React = React;
  return (await import("../components/moderation-panel")).ModerationView;
}

const noop = () => undefined;
const baseProps = { mode: "human", tab: "queue" as const, busy: false, status: "", reason: "", onTab: noop, onReason: noop, onAction: noop, onRefresh: noop };

test("the queue renders each item as text with approve, hide, promote and ban buttons, and markup never becomes elements", async () => {
  const ModerationView = await view();
  const queue = buildQueue({
    submissions: [submission("1", { title: "<img src=x onerror=alert(1)>", note: "<b>note</b>", signals: JSON.stringify([{ source: "humanus", policy: "promotion", detector: "buy-now", severity: "warn", excerpt: "buy now" }]) })],
    comments: [comment("2", { body: "<script>alert(1)</script>" })],
    reports: [report(comment("2").id, { reason: "<i>spam</i>" })],
    handles,
  });
  const html = renderToStaticMarkup(createElement(ModerationView, { ...baseProps, queue, hidden: [], log: [] }));
  assert.ok(html.includes("Queue (2)") && html.includes("Hidden (0)") && html.includes("Recent actions"));
  assert.ok(!html.includes("<img") && !html.includes("<script") && !html.includes("<b>note") && !html.includes("<i>spam"), "reader text is escaped");
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.equal((html.match(/>Approve</g) ?? []).length, 2);
  assert.equal((html.match(/>Hide</g) ?? []).length, 2);
  assert.equal((html.match(/>Promote to a draft</g) ?? []).length, 1, "only the submission can be promoted");
  assert.equal((html.match(/>Ban reader</g) ?? []).length, 2);
  assert.ok(html.includes("Signal (warn): promotion / buy-now"));
  assert.ok(html.includes("Reported: &lt;i&gt;spam&lt;/i&gt;"));
  assert.ok(html.includes("2 reports") === false && html.includes("1 report"));
  assert.ok(html.includes('rel="noopener noreferrer nofollow"'));
  assert.ok(html.includes("quiet-fox (00000000)"));
  assert.ok(html.includes("Only editors and admins can see this."));
});

test("an empty queue, a busy panel and the hidden and log tabs", async () => {
  const ModerationView = await view();
  const empty = renderToStaticMarkup(createElement(ModerationView, { ...baseProps, queue: [], hidden: [], log: [], status: "Done." }));
  assert.ok(empty.includes("Nothing is waiting for a decision.") && empty.includes('role="status"') && empty.includes("Done."));
  const row = buildHidden({ submissions: [submission("1", { state: "hidden" })], comments: [], reports: [], handles });
  const hidden = renderToStaticMarkup(createElement(ModerationView, { ...baseProps, tab: "hidden", queue: [], hidden: row, log: [], busy: true }));
  assert.ok(hidden.includes("Show again") && !hidden.includes(">Hide<") && !hidden.includes(">Approve<"));
  assert.ok(/<button[^>]*disabled[^>]*>Show again/.test(hidden), "controls are disabled while an action is in flight");
  const log = buildActionLog([{ id: "mod-1", by: "human", actorSub: "staff", action: "hide", targetType: "submission", target: "sub-000000000000000000000001", reason: "Spam", fromState: "pending", toState: "hidden", at: "2026-10-22T09:00:00.000Z" }]);
  const logged = renderToStaticMarkup(createElement(ModerationView, { ...baseProps, tab: "log", queue: [], hidden: [], log }));
  assert.ok(logged.includes("Hidden (pending to hidden)") && logged.includes("Spam") && logged.includes(">Undo<"));
  const off = renderToStaticMarkup(createElement(ModerationView, { ...baseProps, mode: "off", queue: [], hidden: [], log: [] }));
  assert.ok(off.includes("Moderation is off"));
});
