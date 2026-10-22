/**
 * A pretend Newsletter service for `?demo=1` and the tests: the same operations and answers as the functions, held in memory.
 * Placeholders only (reader addresses are @example.com); nothing here is a real subscriber, issue or postal address.
 */
import type { NewsletterApi, NewsletterOperation } from "./newsletter-client";
import type {
  NewsletterDelivery,
  NewsletterEvent,
  NewsletterExportRow,
  NewsletterIssue,
  NewsletterList,
  NewsletterSubscriber,
} from "./newsletter-model";

export const FIXTURE_TIME_ZONE = "America/New_York";

const LISTS: NewsletterList[] = [
  { id: "weekly", name: "Weekly roundup", kind: "roundup", confirmed: 412, pending: 17, unsubscribed: 38, timezone: FIXTURE_TIME_ZONE },
  { id: "alerts-security", name: "Security alerts", kind: "alert", confirmed: 96, pending: 4, unsubscribed: 9 },
];

export function fixtureIssues(): NewsletterIssue[] {
  const counts = { queued: 0, sent: 0, failed: 0, suppressed: 0, skipped: 0, delivered: 0, bounced: 0, complained: 0, softBounced: 0 };
  return [
    {
      issueId: "a1", listId: "weekly", listName: "Weekly roundup", kind: "roundup", itemId: "item-weekly-0122", status: "draft",
      subject: "Weekly roundup: Jan 15 to Jan 22, 2027", counts,
    },
    {
      issueId: "a2", listId: "alerts-security", listName: "Security alerts", kind: "alert", itemId: "item-alert-1", status: "awaiting_approval",
      subject: "A critical patch is out for the build tool", counts,
    },
    {
      issueId: "a3", listId: "weekly", listName: "Weekly roundup", kind: "roundup", itemId: "item-weekly-0115", status: "scheduled",
      subject: "Weekly roundup: Jan 8 to Jan 15, 2027", sendAt: "2027-01-15T14:00:00Z", approvedBy: "admin-user", approvedAt: "2027-01-14T18:30:00Z",
      counts, editedSinceApproval: true,
    },
    {
      issueId: "a4", listId: "weekly", listName: "Weekly roundup", kind: "roundup", itemId: "item-weekly-0108", status: "blocked",
      subject: "Weekly roundup: Jan 1 to Jan 8, 2027", sendAt: "2027-01-08T14:00:00Z", note: "postal address missing", counts,
    },
    {
      issueId: "a5", listId: "weekly", listName: "Weekly roundup", kind: "roundup", itemId: "item-weekly-0101", status: "sending",
      subject: "Weekly roundup: Dec 25 to Jan 1, 2027", sendAt: "2027-01-01T14:00:00Z", approvedBy: "admin-user",
      counts: { ...counts, queued: 429, sent: 240, delivered: 188 },
    },
    {
      issueId: "a6", listId: "weekly", listName: "Weekly roundup", kind: "roundup", itemId: "item-weekly-1225", status: "sent",
      subject: "Weekly roundup: Dec 18 to Dec 25, 2026", sendAt: "2026-12-25T14:00:00Z", sentAt: "2026-12-25T14:09:40Z", approvedBy: "admin-user",
      archiveUrl: "https://news.example.com/roundup/2026-12-25.html",
      counts: { ...counts, queued: 421, sent: 418, delivered: 409, bounced: 3, complained: 1, failed: 1, suppressed: 2, softBounced: 2 },
    },
    {
      issueId: "a7", listId: "alerts-security", listName: "Security alerts", kind: "alert", itemId: "item-alert-0", status: "quarantined",
      subject: "An alert with a status this panel does not know", counts,
    },
  ];
}

function deliveriesFor(issueId: string, full: boolean): NewsletterDelivery[] {
  const address = (index: number) => (full ? `reader${index}@example.com` : `r***@example.com`);
  const rows: NewsletterDelivery[] = [
    { address: address(1), status: "delivered", at: "2026-12-25T14:00:04Z", eventAt: "2026-12-25T14:00:09Z" },
    { address: address(2), status: "delivered", at: "2026-12-25T14:00:05Z", eventAt: "2026-12-25T14:00:12Z" },
    { address: address(3), status: "bounced", at: "2026-12-25T14:00:06Z", eventAt: "2026-12-25T14:00:20Z" },
    { address: address(4), status: "complained", at: "2026-12-25T14:00:07Z", eventAt: "2026-12-25T14:02:31Z" },
    { address: address(5), status: "failed", at: "2026-12-25T14:00:08Z", error: "MessageRejected" },
    { address: "(erased)", status: "sent", at: "2026-12-25T14:00:09Z" },
  ];
  return issueId === "a6" || issueId === "a5" ? rows : [];
}

const SUBSCRIBERS: NewsletterSubscriber[] = [
  { email: "reader1@example.com", status: "confirmed", lists: [{ id: "weekly", status: "subscribed" }, { id: "alerts-security", status: "subscribed" }], createdAt: "2026-11-02T10:11:00Z", confirmedAt: "2026-11-02T10:13:00Z" },
  { email: "reader2@example.com", status: "confirmed", lists: [{ id: "weekly", status: "subscribed" }], createdAt: "2026-11-09T08:00:00Z", confirmedAt: "2026-11-09T08:02:00Z" },
  { email: "reader3@example.com", status: "pending", lists: [{ id: "alerts-security", status: "pending" }], createdAt: "2026-12-30T21:45:00Z" },
  { email: "=reader4@example.com", status: "unsubscribed", lists: [{ id: "weekly", status: "unsubscribed" }], createdAt: "2026-10-01T09:00:00Z", confirmedAt: "2026-10-01T09:05:00Z" },
];

const EVENTS: NewsletterEvent[] = [
  { type: "Complaint", at: "2026-12-25T14:02:31Z", issue: "a6", list: "weekly" },
  { type: "Bounce", at: "2026-12-25T14:00:20Z", issue: "a6", list: "weekly", detail: "Permanent" },
  { type: "Delivery", at: "2026-12-25T14:00:12Z", issue: "a6", list: "weekly" },
  { type: "Delivery", at: "2026-12-25T14:00:09Z", issue: "a6", list: "weekly" },
  { type: "Bounce", at: "2026-12-25T13:59:50Z", issue: "a5", list: "weekly", detail: "Transient" },
];

const SAMPLE_HTML = `<!doctype html><html><body style="margin:0;font-family:Georgia,serif;color:#111"><div style="max-width:560px;margin:0 auto;padding:24px"><h1 style="font-size:24px;margin:0 0 12px">Weekly roundup</h1><p>A short introduction goes here.</p><h2 style="font-size:18px">Security</h2><ul><li><a href="#preview">A critical patch is out</a>: update today.</li></ul><hr><p style="font-size:12px;color:#555">You get this because you subscribed. <a href="#preview">Manage</a> &middot; <a href="#preview">Unsubscribe</a><br>1 Example Street, Example City</p></div></body></html>`;

export type FixtureOptions = { postalAddress?: boolean; admin?: boolean };

/** One fixture service per mounted panel, so a demo session keeps its changes until reload. */
export function createFixtureApi(options: FixtureOptions = {}): NewsletterApi {
  const full = options.admin !== false;
  const issues = fixtureIssues();
  const subscribers = [...SUBSCRIBERS];
  const paused = { paused: true, reason: "papyrus-newsletter-example-bounce-rate: bounce rate above 4%", pausedAt: "2026-12-26T09:12:00Z" } as { paused: boolean; reason?: string; pausedAt?: string };
  const findIssue = (input: Record<string, unknown>) => issues.find((issue) => issue.issueId === input.issueId);
  const failure = (error: string, message = "") => ({ ok: false as const, error, message });

  const handlers: Record<NewsletterOperation, (input: Record<string, unknown>) => object> = {
    newsletterOverview: () => ({
      ok: true,
      lists: LISTS,
      totals: { confirmed: 488, pending: 20, unsubscribed: 45 },
      suppressed: 12,
      paused: { ...paused },
      events: EVENTS,
    }),
    newsletterIssues: (input) => ({
      ok: true,
      issues: issues.filter((issue) => (!input.status || issue.status === input.status) && (!input.listId || issue.listId === input.listId)).map(({ editedSinceApproval: _edited, ...rest }) => rest),
    }),
    newsletterIssue: (input) => {
      const issue = findIssue(input);
      return issue ? { ok: true, issue } : failure("not_found");
    },
    newsletterPreview: (input) => {
      const issue = findIssue(input);
      if (!issue) return failure("not_found");
      return { ok: true, subject: issue.subject, html: SAMPLE_HTML, text: `${issue.subject}\n\nA short introduction goes here.\n\nSecurity\n- A critical patch is out: update today.\n\nYou get this because you subscribed.`, bytes: SAMPLE_HTML.length, postalAddress: options.postalAddress !== false };
    },
    newsletterIssueDeliveries: (input) => (findIssue(input) ? { ok: true, deliveries: deliveriesFor(String(input.issueId), full) } : failure("not_found")),
    newsletterSubscribers: (input) => ({
      ok: true,
      subscribers: subscribers.filter((row) => (!input.status || row.status === input.status) && (!input.listId || row.lists.some((entry) => entry.id === input.listId))),
    }),
    newsletterExport: () => ({
      ok: true,
      rows: subscribers.filter((row) => row.status !== "unsubscribed").map((row): NewsletterExportRow => ({
        email: row.email, status: row.status, lists: row.lists.map((entry) => `${entry.id}:${entry.status}`).join(";"), createdAt: row.createdAt,
        consentRequestedAt: row.createdAt, consentConfirmedAt: row.confirmedAt ?? "", consentFormId: "newsletter",
        consentPageUrl: "https://news.example.com/roundup/", consentWording: "Send me the weekly email.",
      })),
    }),
    newsletterApproveIssue: (input) => {
      const issue = findIssue(input);
      if (!issue) return failure("not_found");
      if (!["draft", "awaiting_approval", "scheduled", "blocked"].includes(issue.status)) return failure("invalid_state");
      issue.status = "scheduled";
      issue.sendAt = String(input.sendAt);
      issue.approvedBy = "admin-user";
      delete issue.note;
      delete issue.editedSinceApproval;
      return { ok: true, issue, adjusted: false, warnings: options.postalAddress === false ? ["postal address missing: the send will be blocked until an operator sets it"] : [] };
    },
    newsletterCancelIssue: (input) => {
      const issue = findIssue(input);
      if (!issue) return failure("not_found");
      if (issue.status !== "scheduled") return failure("invalid_state");
      issue.status = "draft";
      issue.note = "cancelled by admin-user";
      delete issue.sendAt;
      delete issue.editedSinceApproval;
      return { ok: true, issue };
    },
    newsletterStopIssue: (input) => {
      const issue = findIssue(input);
      if (!issue) return failure("not_found");
      if (issue.status !== "sending") return failure("invalid_state");
      issue.status = "stopped";
      issue.note = "stopped by admin-user";
      return { ok: true, issue };
    },
    newsletterTestSend: (input) => (findIssue(input) ? { ok: true } : failure("not_found")),
    newsletterCreateDraft: (input) => (input.listId === "weekly" ? { ok: true, status: "exists", issueId: "a1", itemId: "item-weekly-0122" } : failure("bad_request")),
    newsletterErase: (input) => {
      const at = subscribers.findIndex((row) => row.email === input.email);
      if (at >= 0) subscribers.splice(at, 1);
      return { ok: true, removed: at >= 0 ? 3 : 2 };
    },
    newsletterResume: () => {
      paused.paused = false;
      paused.reason = undefined;
      return { ok: true, paused: false };
    },
  };

  return (async (operation: NewsletterOperation, input: Record<string, unknown> = {}) => {
    const admin = ["newsletterApproveIssue", "newsletterCancelIssue", "newsletterStopIssue", "newsletterSubscribers", "newsletterExport", "newsletterErase", "newsletterResume"];
    if (options.admin === false && admin.includes(operation)) return { ok: false, error: "forbidden" };
    return handlers[operation](input);
  }) as NewsletterApi;
}
