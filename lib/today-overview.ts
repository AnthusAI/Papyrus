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

export type TodayOverview = {
  state: "ready";
  asOf: string;
  day: string;
  timeZone: string;
  start: string;
  end: string;
  rows: TodayRow[];
  didNotRun: TodayDidNotRun[];
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
