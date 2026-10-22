/** Shapes and wording for the newsroom Newsletter panel. `src/papyrus_content/newsletter/` (panel.py, issues.py) produces them. */
import { getNewsroomNavHref } from "./newsroom-nav";
import { csvCell } from "./signup-csv";

export type NewsletterCounts = Partial<Record<"queued" | "sent" | "failed" | "suppressed" | "skipped" | "delivered" | "bounced" | "complained" | "softBounced", number>>;

export type NewsletterList = { id: string; name: string; kind: string; confirmed: number; pending: number; unsubscribed: number; timezone?: string };

export type NewsletterEvent = { type: string; at: string; issue?: string; list?: string; detail?: string };

export type NewsletterOverview = {
  lists: NewsletterList[];
  totals: { confirmed: number; pending: number; unsubscribed: number };
  suppressed: number;
  paused: { paused: boolean; reason?: string; pausedAt?: string; resumedAt?: string };
  events: NewsletterEvent[];
};

export type NewsletterIssue = {
  issueId: string;
  listId: string;
  listName?: string;
  kind: string;
  itemId?: string;
  subject: string;
  status: string;
  sendAt?: string;
  approvedBy?: string;
  approvedAt?: string;
  sentAt?: string;
  counts: NewsletterCounts;
  note?: string;
  archiveUrl?: string;
  editedSinceApproval?: boolean;
};

export type NewsletterPreview = { subject: string; html: string; text: string; bytes: number; postalAddress: boolean };

export type NewsletterDelivery = { address: string; status: string; at: string; eventAt?: string; error?: string };

export type NewsletterSubscriber = { email: string; status: string; lists: { id: string; status: string }[]; createdAt: string; confirmedAt?: string };

export type NewsletterExportRow = {
  email: string;
  status: string;
  lists: string;
  createdAt: string;
  consentRequestedAt: string;
  consentConfirmedAt: string;
  consentFormId: string;
  consentPageUrl: string;
  consentWording: string;
};

export type NewsletterFailure = { ok: false; error: string; message?: string };

/** The newsroom words for the statuses the functions write. A status this panel does not know is shown as written, never hidden. */
const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  awaiting_approval: "Awaiting approval",
  scheduled: "Scheduled",
  sending: "Sending",
  sent: "Sent",
  stopped: "Stopped",
  cancelled: "Cancelled",
  blocked: "Blocked",
};
/** A mark beside the word, so no status relies on colour alone. */
const STATUS_MARKS: Record<string, string> = { draft: "✎", awaiting_approval: "?", scheduled: "◷", sending: "▶", sent: "✓", stopped: "■", cancelled: "–", blocked: "!" };

export function statusLabel(status: string): string {
  if (STATUS_LABELS[status]) return STATUS_LABELS[status];
  const words = status.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown";
}

export function statusMark(status: string): string {
  return STATUS_MARKS[status] ?? "·";
}

export const ISSUE_STATUS_FILTERS = ["draft", "awaiting_approval", "scheduled", "sending", "sent", "blocked", "stopped", "cancelled"] as const;

/** Approval accepts a draft, an alert awaiting approval, a scheduled issue (a new time) and a blocked one (cause fixed). */
export function canApprove(status: string): boolean {
  return status === "draft" || status === "awaiting_approval" || status === "scheduled" || status === "blocked";
}
export const canCancel = (status: string): boolean => status === "scheduled";
export const canStop = (status: string): boolean => status === "sending";

export function issueEditorHref(itemId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(itemId)}`, demo);
}

const ERROR_WORDS: Record<string, string> = {
  forbidden: "Your role cannot do this.",
  not_found: "That issue no longer exists.",
  invalid_state: "The issue changed state. Refresh and try again.",
  item_missing: "The issue's item no longer exists.",
  render_failed: "The issue cannot be rendered. Open it in the editor and fix the body.",
  bad_request: "The request was not understood.",
  no_address: "Your account has no email address to send a test to.",
  unavailable: "The newsletter service could not be reached. Try again in a minute.",
};

/** One sentence for a failed operation. A missing postal address is an operator task, so the panel says where it is set. */
export function failureText(failure: NewsletterFailure): string {
  if (failure.error === "postal_address_missing") {
    return "This site has no postal address for the email footer, and mail law requires one. An operator sets it in the site's AWS configuration (an SSM parameter); it cannot be set from the newsroom.";
  }
  return ERROR_WORDS[failure.error] ?? failure.message ?? "The request failed.";
}

// -- times ---------------------------------------------------------------------------------------------------------------

export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "never";
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return match ? `${match[1]} ${match[2]} UTC` : iso;
}

export function validTimeZone(zone: string | null | undefined): string | null {
  if (!zone) return null;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return zone;
  } catch {
    return null;
  }
}

function wallParts(instant: Date, zone: string): { year: number; month: number; day: number; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(instant);
  const pick = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? "0");
  return { year: pick("year"), month: pick("month"), day: pick("day"), hour: pick("hour") % 24, minute: pick("minute") };
}

/** Minutes the zone is ahead of UTC at that instant. */
function offsetMinutes(instant: Date, zone: string): number {
  const wall = wallParts(instant, zone);
  const asUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  return Math.round((asUtc - Math.floor(instant.getTime() / 60000) * 60000) / 60000);
}

const pad = (value: number) => String(value).padStart(2, "0");

/** Local wall time `YYYY-MM-DDTHH:mm` (a datetime-local value) as an ISO instant, for the given zone. */
export function zonedInputToIso(local: string, zone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match.map(Number) as unknown as number[];
  const wallAsUtc = Date.UTC(year, month - 1, day, hour, minute);
  let guess = wallAsUtc - offsetMinutes(new Date(wallAsUtc), zone) * 60000;
  guess = wallAsUtc - offsetMinutes(new Date(guess), zone) * 60000; // once more: the offset can differ across a clock change
  const instant = new Date(guess);
  return Number.isNaN(instant.getTime()) ? null : instant.toISOString().replace(".000Z", "Z");
}

/** The next whole hour on the zone's clock, as a datetime-local value. */
export function nextWholeHourInput(now: Date, zone: string): string {
  const wall = wallParts(now, zone);
  const next = new Date(Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour + 1, 0));
  return `${next.getUTCFullYear()}-${pad(next.getUTCMonth() + 1)}-${pad(next.getUTCDate())}T${pad(next.getUTCHours())}:00`;
}

/** An ISO instant as a datetime-local value in the zone. */
export function isoToZonedInput(iso: string, zone: string): string {
  const wall = wallParts(new Date(iso), zone);
  return `${wall.year}-${pad(wall.month)}-${pad(wall.day)}T${pad(wall.hour)}:${pad(wall.minute)}`;
}

/** `2027-01-15 09:00 EST` in the zone. */
export function formatInZone(iso: string | null | undefined, zone: string): string {
  if (!iso) return "not set";
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return iso;
  const label = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "short" }).formatToParts(instant).find((part) => part.type === "timeZoneName")?.value ?? zone;
  return `${isoToZonedInput(iso, zone).replace("T", " ")} ${label}`;
}

// -- counts and CSV ------------------------------------------------------------------------------------------------------

/** "12 sent, 2 delivered, 1 bounced"; only counters above zero, in reading order. */
export function countsText(counts: NewsletterCounts): string {
  const order: [keyof NewsletterCounts, string][] = [
    ["queued", "queued"], ["sent", "sent"], ["delivered", "delivered"], ["bounced", "bounced"], ["complained", "complained"],
    ["failed", "failed"], ["suppressed", "suppressed"], ["skipped", "skipped"], ["softBounced", "soft bounced"],
  ];
  const parts = order.filter(([name]) => (counts[name] ?? 0) > 0).map(([name, label]) => `${counts[name]} ${label}`);
  return parts.length ? parts.join(", ") : "nothing sent yet";
}

export const NEWSLETTER_CSV_HEADER = [
  "email", "status", "lists", "createdAt", "consentRequestedAt", "consentConfirmedAt", "consentFormId", "consentPageUrl", "consentWording",
] as const;

/** Every cell goes through the formula neutraliser: addresses and consent wording are text people typed. */
export function subscribersToCsv(rows: NewsletterExportRow[]): string {
  const lines = rows.map((row) => NEWSLETTER_CSV_HEADER.map((column) => csvCell(String(row[column] ?? ""))).join(","));
  return `${[NEWSLETTER_CSV_HEADER.join(","), ...lines].join("\r\n")}\r\n`;
}
