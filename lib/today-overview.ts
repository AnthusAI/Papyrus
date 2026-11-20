/** Shapes and wording for Today: what ran in one day, what it decided to do nothing about, and what it cost (PPY-5bcf42).
 *  src/papyrus_content/today.py produces them; the words match what `papyrus today` prints. */
import { getNewsroomNavHref } from "./newsroom-nav";

export type TodayOutcome = "acted" | "nothing" | "asked" | "failed" | "unknown";
export type TodayCountKey = TodayOutcome | "notFinished" | "beforeOutcomes";
export type TodayCounts = Record<TodayCountKey, number>;

export type TodayRun = {
  runId: string | null;
  procedureKey: string | null;
  automationId: string | null;
  requestedAt: string | null;
  finishedAt: string | null;
  runStatus: string | null;
  outcome: TodayOutcome | null;
  outcomeReason: string | null;
  /** The outcome in words with its mark, as the command line prints it. */
  outcomeShown: string;
  rung: string | null;
  subjectKind: string | null;
  subjectId: string | null;
  costUsd: number | null;
  error: string | null;
};

export type TodayCosts = { costUsd: number; costKnownRuns: number; costUnknownRuns: number };

export type TodayRow = TodayCosts & {
  key: string;
  kind: "responsibility" | "automation" | "procedure";
  title: string;
  counts: TodayCounts;
  /** Outcome to reason code to how many runs. */
  reasons: Partial<Record<TodayOutcome, Record<string, number>>>;
  automationIds: string[];
  runs: TodayRun[];
};

export type TodayDidNotRun = { automationId: string; title: string; state: "Did not run"; whyCode: "disabled" | "unsupported" | "no_wake"; why: string };

export type TodaySendCounts = Record<"queued" | "sent" | "failed" | "suppressed" | "skipped" | "delivered" | "bounced" | "complained", number>;

/** One email send: an email Delivery of an Announcement released in the day, with the counts Caducus's records add up to. */
export type TodaySend = {
  deliveryId: string;
  announcementId: string;
  kind: string;
  releasedAt: string;
  lists: string[];
  items: number;
  state: string;
  /** Where the send stands as a mark and its words, as the command line prints it. */
  stateShown: string;
  /** The same words without the mark: the page draws its own mark (a Lucide icon). */
  stateWords: string;
  attempts: number;
  lastAttempt: string | null;
  counts: TodaySendCounts;
  countsText: string;
  /** What Caducus charged, a decimal string, or null when nothing was charged. */
  cost: string | null;
};

/** A record whose due time passed long enough ago that no wake is in flight and that nothing ran for (src/papyrus_content/overdue.py). */
export type TodayOverdue = {
  kind: string;
  id: string;
  dueAt: string;
  waitingFor: string | null;
  /** The one flag raised for this record and the time it missed. */
  flagId: string;
  /** The words with their mark, as the command line prints it. */
  shown: string;
};

export type TodayOverview = {
  state: "ready";
  asOf: string;
  day: string;
  timeZone: string;
  start: string;
  end: string;
  overdue: TodayOverdue[];
  rows: TodayRow[];
  didNotRun: TodayDidNotRun[];
  sends: TodaySend[];
  totals: TodayCosts & { runs: number; counts: TodayCounts };
};

export type TodayResult = TodayOverview | { state: "unavailable" } | { error: "forbidden" | "bad_request"; message?: string };

/** Each outcome's words, in the order Today lists them. The mark beside them is a Lucide icon (components/today-view.tsx). */
export const OUTCOME_WORDS: Record<TodayOutcome, string> = {
  acted: "Did it",
  nothing: "Nothing to do",
  asked: "Asked",
  failed: "Failed",
  unknown: "Outcome unknown",
};
export const OTHER_WORDS: Record<"notFinished" | "beforeOutcomes", string> = {
  notFinished: "Not finished yet",
  beforeOutcomes: "Recorded before outcomes",
};
/** The words of each send count, in the order a send lists them. A count of zero is left out; a send with none says so. */
export const SEND_COUNT_WORDS: Record<keyof TodaySendCounts, string> = {
  queued: "Queued", sent: "Sent", failed: "Failed", suppressed: "Suppressed", skipped: "Skipped", delivered: "Delivered", bounced: "Bounced", complained: "Complained",
};
export const SEND_COUNT_ORDER = Object.keys(SEND_COUNT_WORDS) as (keyof TodaySendCounts)[];

export const NO_SEND_COST = "no cost recorded";

export function sendCostText(cost: string | null): string {
  return cost === null ? NO_SEND_COST : dollars(Number(cost));
}

export function sendItemsText(items: number): string {
  return `${items} item${items === 1 ? "" : "s"}`;
}

export const OUTCOME_ORDER: TodayOutcome[] = ["acted", "nothing", "asked", "failed", "unknown"];
export const OTHER_ORDER: ("notFinished" | "beforeOutcomes")[] = ["notFinished", "beforeOutcomes"];

export function countWords(key: TodayCountKey): string {
  return key in OUTCOME_WORDS ? OUTCOME_WORDS[key as TodayOutcome] : OTHER_WORDS[key as "notFinished" | "beforeOutcomes"];
}

export function dollars(value: number): string {
  return value === 0 || value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

export function runsText(count: number): string {
  return `${count} run${count === 1 ? "" : "s"}`;
}

/** "$0.41", with how many runs recorded no cost when some did not. A run without a recorded cost is never counted as free. */
export function costText(costs: TodayCosts): string {
  const { costKnownRuns: known, costUnknownRuns: unknown } = costs;
  if (!known && !unknown) return "no runs";
  if (!known) return `cost unknown for ${runsText(unknown)}`;
  return unknown ? `${dollars(costs.costUsd)} (cost unknown for ${runsText(unknown)})` : dollars(costs.costUsd);
}

export function reasonsText(reasons: Record<string, number>): string {
  return Object.entries(reasons).sort(([a], [b]) => a.localeCompare(b)).map(([code, count]) => `${count} ${code}`).join(", ");
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "Monday 16 November 2026" for a YYYY-MM-DD day, in English whatever the viewer's locale, and in UTC so no time zone can move it. */
export function dayTitle(day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(date.getTime())) return day;
  return `${WEEKDAYS[date.getUTCDay()]} ${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

/** The Automation page, with one automation's runs open when the line names one. */
export function automationsHref(automationId: string | null, demo?: boolean): string {
  const base = getNewsroomNavHref("/newsroom/administration/automations", demo);
  return automationId ? `${base}${base.includes("?") ? "&" : "?"}automation=${encodeURIComponent(automationId)}` : base;
}

export const REFRESH_MILLISECONDS = 5 * 60 * 1000;
