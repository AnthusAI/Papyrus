import type { CyclotronStatus } from "cyclotron/cyclotron-status";
import { isCyclotronStatus } from "cyclotron/cyclotron-status";

/**
 * The Cyclotron classifier behind this site's predictions, as the newsroom home page shows it.
 *
 * Version 1 reads only what Cyclotron already publishes: the `status` snapshot (`cyclotron-status/v1`), which the monitoring router keeps
 * one row of per publication (`cyclotron-status` task, src/papyrus_content/monitoring_router.py) and the Monitoring view serves for the
 * signed-in site's own publication only (list `cyclotronStatus`). The fixed rule for every sentence here: say only what the snapshot
 * says, never imply learning that did not happen, and say "Not measured yet" for a number that is missing.
 *
 * SEAM FOR THE `report` OPERATION. Cyclotron has proposed a richer read-only `report` (history over time, and the supporting questions behind a
 * decision) that is not published. Nothing here is built against a draft of it. When it ships, add its rows beside `HostedStatusRow`, load
 * them next to the status rows in `loadCyclotronStatusRows` (lib/monitoring-client.ts) and render them through the `extra` slot of
 * `HomeCyclotronPanel` (components/home-cyclotron-panel.tsx). Until then the panel shows no history and no supporting question, not even a placeholder.
 */

/** One row the Monitoring view serves: this publication's output and its latest snapshot. */
export type HostedStatusRow = {
  monitorId: string;
  publicationId: string;
  output: string | null;
  /** When the Cyclotron produced the snapshot: as fresh as the binding's last completed decision. */
  asOf: string | null;
  /** When the router last asked. */
  checkedAt: string | null;
  status: CyclotronStatus;
};

/** What the home page knows about the classifier. `none` means the read worked and there is no snapshot yet. */
export type HomeCyclotronState =
  | { state: "loading" }
  | { state: "unavailable" }
  | { state: "none" }
  | { state: "ready"; rows: HostedStatusRow[] };

/** Keeps the rows that carry a real v1 snapshot. Anything else is dropped rather than shown half-read. */
export function parseHostedStatusRows(value: unknown): HostedStatusRow[] {
  const rows = (value as { rows?: unknown } | null)?.rows;
  if (!Array.isArray(rows)) return [];
  const parsed: HostedStatusRow[] = [];
  for (const row of rows) {
    const candidate = row as Partial<HostedStatusRow> | null;
    if (!candidate || typeof candidate !== "object" || !isCyclotronStatus(candidate.status)) continue;
    parsed.push({
      monitorId: String(candidate.monitorId ?? ""),
      publicationId: String(candidate.publicationId ?? ""),
      output: typeof candidate.output === "string" ? candidate.output : null,
      asOf: typeof candidate.asOf === "string" ? candidate.asOf : candidate.status.asOf ?? null,
      checkedAt: typeof candidate.checkedAt === "string" ? candidate.checkedAt : null,
      status: candidate.status,
    });
  }
  return parsed;
}

/** One block per output: when several monitors report the same output, the newest snapshot wins. */
export function newestPerOutput(rows: readonly HostedStatusRow[]): HostedStatusRow[] {
  const best = new Map<string, HostedStatusRow>();
  for (const row of rows) {
    const key = `${row.publicationId}\u0000${row.output ?? row.status.cyclotron.id}`;
    const held = best.get(key);
    if (!held || String(row.asOf ?? "") > String(held.asOf ?? "")) best.set(key, row);
  }
  return [...best.values()].sort((left, right) => String(right.asOf ?? "").localeCompare(String(left.asOf ?? "")));
}

export function homeCyclotronStateFrom(value: unknown): HomeCyclotronState {
  if (!value || typeof value !== "object") return { state: "unavailable" };
  const raw = value as { error?: unknown; state?: unknown; rows?: unknown };
  if (raw.error || raw.state === "unavailable") return { state: "unavailable" };
  const rows = newestPerOutput(parseHostedStatusRows(value));
  return rows.length ? { state: "ready", rows } : { state: "none" };
}

// --- the words ---------------------------------------------------------------------------------------------------------

export const NO_SNAPSHOT_SENTENCE =
  "The Cyclotron has not reported on this site's classifier yet. A status appears here after the classifier's first completed decisions.";
export const UNAVAILABLE_SENTENCE = "The classifier's status could not be read right now. Try again in a minute.";
export const NOT_MEASURED = "Not measured yet";
export const NO_RETRAINING_SENTENCE = "No retraining has happened yet.";

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

function percent(value: number | null | undefined): string | null {
  return value == null || !Number.isFinite(value) ? null : `${Math.round(value * 100)}%`;
}

/** A date and time in the viewer's zone (tests pass a zone). An unreadable value is shown as it came. */
export function formatWhen(value: string | null | undefined, timeZone?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", ...(timeZone ? { timeZone } : {}) }).format(date);
}

function formatDay(value: string | null | undefined, timeZone?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", ...(timeZone ? { timeZone } : {}) }).format(date);
}

const CHANGE_WORDS: Record<NonNullable<CyclotronStatus["lastChange"]>["kind"], string> = {
  refit: "retrained on reviews",
  promoted: "improved",
  dropped: "tried a change and kept the current approach",
  definition: "questions or examples changed",
};

export type ClassifierFacts = {
  /** The classifier's own name from the snapshot, for example `relevant`. */
  name: string;
  /** True when the snapshot says the classifier was retrained or changed at least once. */
  retrained: boolean;
  retraining: string;
  /** The evaluation number as a percentage, or null when it was not measured. */
  agreement: string | null;
  evaluation: string;
  evaluationNote: string;
  counts: string[];
  snapshot: string;
  freshness: string;
};

/** Every sentence for one classifier block, from its snapshot alone. */
export function describeClassifier(row: HostedStatusRow, options: { timeZone?: string } = {}): ClassifierFacts {
  const { status } = row;
  const { timeZone } = options;
  const refits = Math.max(0, Number(status.cyclotron.refits) || 0);
  const change = status.lastChange;

  let retraining: string;
  if (!change && refits === 0) {
    retraining = NO_RETRAINING_SENTENCE;
  } else {
    const parts: string[] = [];
    parts.push(refits === 0 ? "No retraining on reviews has happened yet." : `Retrained ${plural(refits, "time")}.`);
    if (change) {
      const day = formatDay(change.at, timeZone);
      const summary = (change.plainSummary ?? change.summary ?? "").trim();
      parts.push(`Last change${day ? ` ${day}` : " (date not recorded)"}: ${CHANGE_WORDS[change.kind] ?? "changed"}${summary ? `, ${summary}` : ""}.`);
    } else {
      parts.push("The date of the last retraining was not recorded.");
    }
    retraining = parts.join(" ");
  }

  const alignment = status.alignment;
  const agreement = percent(alignment.accuracy);
  const measuredOn = (alignment.measuredOn ?? "").trim();
  const evaluation = agreement ? `Agreement with reviewers ${agreement}` : `Agreement with reviewers: ${NOT_MEASURED}`;
  const evaluationNote = alignment.labels > 0
    ? `Measured on ${measuredOn || "reviewed decisions"}: ${plural(alignment.labels, "review")} in the last ${alignment.window}.`
    : `No reviews have been counted yet${measuredOn ? ` (measured on ${measuredOn})` : ""}.`;

  const counts = [
    alignment.labels > 0 ? `${plural(alignment.labels, "reviewed label")} counted` : "No reviewed labels counted yet",
    `${status.pending.decisionsAwaitingReview} awaiting review`,
    ...(status.cyclotron.primedExamples ? [`Started with ${plural(status.cyclotron.primedExamples, "reference")}`] : []),
  ];

  const asOf = formatWhen(status.asOf ?? row.asOf, timeZone);
  const checked = formatWhen(row.checkedAt, timeZone);
  return {
    name: status.cyclotron.classifier,
    retrained: refits > 0 || change !== null,
    retraining,
    agreement,
    evaluation,
    evaluationNote,
    counts,
    snapshot: asOf ? `Snapshot from ${asOf}` : "Snapshot time not recorded",
    freshness: `Votes after the snapshot are not included yet.${checked ? ` Checked ${checked}.` : ""}`,
  };
}
