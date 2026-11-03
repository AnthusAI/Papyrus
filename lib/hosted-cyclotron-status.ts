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
 * THE `report` OPERATION (`cyclotron-classifier-report/v1`, Cyclotron src/decision_flywheel/classifier_report.py). The same hourly task also reads the
 * Cyclotron's read-only `report` and keeps this publication's own output beside the snapshot in the same row (`report`, `reportCheckedAt`).
 * Either may be missing: a site on an older Papyrus version, and any row before the router's first run, has no report; a report can exist before a
 * first decision, when there is no snapshot. `parseHostedReport` keeps only a complete v1 report; `describeReport` turns it into sentences
 * (learning, the most recent cycle, agreement with reviewers by day and by classifier revision, the held-out evaluation, counts, and the decision
 * elements: question, classes, rubric, supporting questions and weights). Every string in a report is text and is never rendered as HTML.
 * Agreement is never called accuracy: reviewers choose what they vote on. When `compared` is 0 the panel says "Not compared yet", never 0%.
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
  /** Null when the row holds only a report (the Cyclotron has completed no decision for this classifier yet). */
  status: CyclotronStatus | null;
  /** The classifier report, when the router has read one. Absent on rows written before the report existed. */
  report?: ClassifierReport | null;
  /** When the router last read the report. */
  reportCheckedAt?: string | null;
};

export const REPORT_SCHEMA = "cyclotron-classifier-report/v1";

export type AgreementCounts = { votes: number; compared: number; agreed: number };
/** One output's `cyclotron-classifier-report/v1` section, as the router stores it (the router adds `schema` and `generatedAt`). */
export type ClassifierReport = {
  schema: typeof REPORT_SCHEMA;
  generatedAt: string | null;
  classifier: { id: string; revision: number | string | null; question: string; criteriaFingerprint: string | null; rubric: string; classes: string[] };
  learning: {
    state: string; reason: string | null; version: number | null; refits: number | null;
    lastChange: NonNullable<CyclotronStatus["lastChange"]> | null; asOf: string | null; unavailableReason: string | null;
  };
  agreement: AgreementCounts & {
    byClassifierRevision: (AgreementCounts & { classifierRevision: string })[];
    byDay: (AgreementCounts & { day: string })[];
  };
  heldOut: { accuracy: number | null; reason: string | null };
  counts: { labels: Record<string, number>; reviewedDecisions: number | null; primedExamples: number | null; decisionsAwaitingReview: number | null };
  model: { features: unknown; weights: unknown; reason: string | null };
  /** What the router cut from this report to keep its row under the table's item limit, if anything. */
  trimmed: string[];
};

/** What the home page knows about the classifier. `none` means the read worked and there is no snapshot yet. */
export type HomeCyclotronState =
  | { state: "loading" }
  | { state: "unavailable" }
  | { state: "none" }
  | { state: "ready"; rows: HostedStatusRow[] };

const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null);
const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

function agreementCounts(value: unknown): AgreementCounts | null {
  if (!isObject(value)) return null;
  const votes = count(value.votes), compared = count(value.compared), agreed = count(value.agreed);
  return votes === null || compared === null || agreed === null || agreed > compared ? null : { votes, compared, agreed };
}

function agreementList<K extends string>(value: unknown, key: K): (AgreementCounts & Record<K, string>)[] | null {
  if (!Array.isArray(value)) return null;
  const list: (AgreementCounts & Record<K, string>)[] = [];
  for (const entry of value) {
    const counts = agreementCounts(entry);
    const label = isObject(entry) ? entry[key] : null;
    if (!counts || (typeof label !== "string" && typeof label !== "number")) return null;
    list.push({ ...counts, [key]: String(label) } as AgreementCounts & Record<K, string>);
  }
  return list;
}

/** A complete v1 report, or null. An unknown schema or a section that is not in the v1 shape drops the whole report rather than showing half of it. */
export function parseHostedReport(value: unknown): ClassifierReport | null {
  if (!isObject(value) || value.schema !== REPORT_SCHEMA) return null;
  const { classifier, learning, agreementWithEditors, heldOut, counts, model } = value as Record<string, unknown>;
  if (!isObject(classifier) || !isObject(learning) || !isObject(heldOut) || !isObject(counts) || !isObject(model)) return null;
  if (typeof classifier.id !== "string" || typeof classifier.question !== "string" || !Array.isArray(classifier.classes)) return null;
  const overall = agreementCounts(agreementWithEditors);
  const agreement = isObject(agreementWithEditors) ? agreementWithEditors : {};
  const byDay = agreementList(agreement.byDay, "day");
  const byClassifierRevision = agreementList(agreement.byClassifierRevision, "classifierRevision");
  if (!overall || !byDay || !byClassifierRevision || typeof learning.state !== "string") return null;
  const labels: Record<string, number> = {};
  if (counts.labels != null && !isObject(counts.labels)) return null;
  for (const [label, number] of Object.entries((counts.labels as Record<string, unknown> | null) ?? {})) {
    const parsed = count(number);
    if (parsed === null) return null;
    labels[label] = parsed;
  }
  const change = isObject(learning.lastChange) && typeof learning.lastChange.kind === "string" ? (learning.lastChange as unknown as NonNullable<CyclotronStatus["lastChange"]>) : null;
  return {
    schema: REPORT_SCHEMA,
    generatedAt: text(value.generatedAt),
    classifier: {
      id: classifier.id, revision: typeof classifier.revision === "number" || typeof classifier.revision === "string" ? classifier.revision : null,
      question: classifier.question, criteriaFingerprint: text(classifier.criteriaFingerprint), rubric: text(classifier.rubric) ?? "",
      classes: classifier.classes.filter((entry): entry is string => typeof entry === "string"),
    },
    learning: {
      state: learning.state, reason: text(learning.reason), version: count(learning.version), refits: count(learning.refits),
      lastChange: change, asOf: text(learning.asOf), unavailableReason: text(learning.unavailableReason),
    },
    agreement: { ...overall, byClassifierRevision, byDay },
    heldOut: { accuracy: typeof heldOut.accuracy === "number" && Number.isFinite(heldOut.accuracy) ? heldOut.accuracy : null, reason: text(heldOut.reason) },
    counts: { labels, reviewedDecisions: count(counts.reviewedDecisions), primedExamples: count(counts.primedExamples), decisionsAwaitingReview: count(counts.decisionsAwaitingReview) },
    model: { features: model.features ?? null, weights: model.weights ?? null, reason: text(model.reason) },
    trimmed: Array.isArray(value.trimmed) ? value.trimmed.filter((entry): entry is string => typeof entry === "string") : [],
  };
}

/** Keeps the rows that carry a real v1 snapshot or a real v1 report. Anything else is dropped rather than shown half-read. */
export function parseHostedStatusRows(value: unknown): HostedStatusRow[] {
  const rows = (value as { rows?: unknown } | null)?.rows;
  if (!Array.isArray(rows)) return [];
  const parsed: HostedStatusRow[] = [];
  for (const row of rows) {
    const candidate = row as (Partial<Omit<HostedStatusRow, "report">> & { report?: unknown }) | null;
    if (!candidate || typeof candidate !== "object") continue;
    const status = isCyclotronStatus(candidate.status) ? candidate.status : null;
    const report = parseHostedReport(candidate.report);
    if (!status && !report) continue;
    parsed.push({
      monitorId: String(candidate.monitorId ?? ""),
      publicationId: String(candidate.publicationId ?? ""),
      output: typeof candidate.output === "string" ? candidate.output : null,
      asOf: typeof candidate.asOf === "string" ? candidate.asOf : status?.asOf ?? null,
      checkedAt: typeof candidate.checkedAt === "string" ? candidate.checkedAt : null,
      status,
      report,
      reportCheckedAt: typeof candidate.reportCheckedAt === "string" ? candidate.reportCheckedAt : null,
    });
  }
  return parsed;
}

/** The classifier's own id for a row, from the snapshot or the report. */
export function outputOf(row: HostedStatusRow): string {
  return row.output ?? row.status?.cyclotron.id ?? row.report?.classifier.id ?? "";
}

/** When a row was last fresh: the snapshot's time, else the report's. */
function rowTime(row: HostedStatusRow): string {
  return String(row.asOf ?? row.report?.generatedAt ?? row.reportCheckedAt ?? "");
}

/** One block per output: when several monitors report the same output, the newest snapshot wins. */
export function newestPerOutput(rows: readonly HostedStatusRow[]): HostedStatusRow[] {
  const best = new Map<string, HostedStatusRow>();
  for (const row of rows) {
    const key = `${row.publicationId}\u0000${outputOf(row)}`;
    const held = best.get(key);
    if (!held || rowTime(row) > rowTime(held)) best.set(key, row);
  }
  return [...best.values()].sort((left, right) => rowTime(right).localeCompare(rowTime(left)));
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
export const NO_RETRAINING_SENTENCE = "Not cycled yet.";

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
  refit: "cycled on reviews",
  promoted: "new version promoted",
  dropped: "tried a change and kept the current approach",
  definition: "questions or examples changed",
};

/** The most recent cycle in words, from the number of cycles and the last change. Never implies learning that did not happen. */
export function cycleSentence(refits: number, change: CyclotronStatus["lastChange"] | null, timeZone?: string): string {
  if (!change && refits === 0) return NO_RETRAINING_SENTENCE;
  const parts: string[] = [];
  parts.push(refits === 0 ? "Not cycled on reviews yet." : `Cycled ${plural(refits, "time")}.`);
  if (change) {
    const day = formatDay(change.at, timeZone);
    const summary = (change.plainSummary ?? change.summary ?? "").trim().replace(/\.+$/, "");
    parts.push(`Last change${day ? ` ${day}` : " (date not recorded)"}: ${CHANGE_WORDS[change.kind] ?? "changed"}${summary ? `, ${summary}` : ""}.`);
  } else {
    parts.push("The date of the last cycle was not recorded.");
  }
  return parts.join(" ");
}

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
export function describeClassifier(row: HostedStatusRow & { status: CyclotronStatus }, options: { timeZone?: string } = {}): ClassifierFacts {
  const { status } = row;
  const { timeZone } = options;
  const refits = Math.max(0, Number(status.cyclotron.refits) || 0);
  const change = status.lastChange;

  const retraining = cycleSentence(refits, change, timeZone);

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

// --- the report's words ------------------------------------------------------------------------------------------------

export const NOT_COMPARED = "Not compared yet";
export const AGREEMENT_NOT_ACCURACY = "This is agreement, not accuracy: reviewers choose what they vote on.";

export type DayAgreement = {
  day: string;
  label: string;
  /** agreed / compared, 0 to 1, or null when nothing was compared that day. */
  share: number | null;
  words: string;
};

export type ReportFacts = {
  learning: string;
  learningReason: string | null;
  cycle: string;
  version: string | null;
  agreement: string;
  agreementNote: string;
  daysNote: string;
  days: DayAgreement[];
  earlierDays: number;
  revisions: string[];
  heldOut: string;
  counts: string[];
  awaiting: string | null;
  snapshot: string;
  /** The decision elements, for the expanded details. */
  question: string;
  classes: string;
  rubric: string | null;
  supporting: { rows: { name: string; weight: string | null }[]; reason: string | null };
  trimmed: string | null;
};

/** How many days the compact list shows; earlier ones are counted in words. */
export const DAYS_SHOWN = 7;

function agreementWords(entry: AgreementCounts): string {
  if (entry.compared === 0) return entry.votes > 0 ? `${NOT_COMPARED.toLowerCase()} (${plural(entry.votes, "vote")})` : "no votes";
  return `${entry.agreed} of ${entry.compared} compared`;
}

/** The model's features and weights as name and weight rows, whatever shape they arrive in, or an empty list when neither is present or readable. */
export function modelRows(model: ClassifierReport["model"]): { name: string; weight: string | null }[] {
  const { features, weights } = model;
  const weight = (value: unknown): string | null => (typeof value === "number" && Number.isFinite(value) ? String(Math.round(value * 1000) / 1000) : null);
  if (isObject(weights)) return Object.entries(weights).map(([name, value]) => ({ name, weight: weight(value) }));
  if (Array.isArray(features)) {
    return features.flatMap((feature, index) => {
      if (typeof feature === "string") return [{ name: feature, weight: Array.isArray(weights) ? weight(weights[index]) : null }];
      if (isObject(feature) && typeof feature.name === "string") return [{ name: feature.name, weight: weight(feature.weight) ?? (Array.isArray(weights) ? weight(weights[index]) : null) }];
      return [];
    });
  }
  return [];
}

/** Every sentence for the report part of one classifier block. */
export function describeReport(report: ClassifierReport, options: { timeZone?: string } = {}): ReportFacts {
  const { timeZone } = options;
  const { learning, agreement, counts } = report;
  const days = [...agreement.byDay].sort((a, b) => b.day.localeCompare(a.day));
  const shown: DayAgreement[] = days.slice(0, DAYS_SHOWN).map((entry) => ({
    day: entry.day,
    label: formatDay(`${entry.day}T12:00:00Z`, "UTC") ?? entry.day,
    share: entry.compared > 0 ? entry.agreed / entry.compared : null,
    words: agreementWords(entry),
  }));
  const comparedDays = days.filter((entry) => entry.compared > 0).length;
  const reviewed = Object.values(counts.labels).reduce((sum, value) => sum + value, 0);
  const labelWords = Object.entries(counts.labels).map(([label, number]) => `${label} ${number}`);
  const asOf = formatWhen(learning.asOf ?? report.generatedAt, timeZone);
  const snapshot = learning.unavailableReason
    ? `No snapshot yet: ${learning.unavailableReason}.`.replace(/\.\.$/, ".")
    : asOf ? `Report from ${asOf}` : "Report time not recorded";

  let agreementLine: string;
  let agreementNote: string;
  if (agreement.compared === 0) {
    agreementLine = `Agreement with reviewers: ${NOT_COMPARED}`;
    agreementNote = agreement.votes > 0
      ? `${plural(agreement.votes, "vote")} recorded, none yet matched with a decision to compare against. ${AGREEMENT_NOT_ACCURACY}`
      : `No votes recorded yet. ${AGREEMENT_NOT_ACCURACY}`;
  } else {
    agreementLine = `Agreement with reviewers: ${agreement.agreed} of ${agreement.compared} compared`;
    const uncompared = agreement.votes - agreement.compared;
    agreementNote = `${plural(agreement.votes, "vote")} recorded${uncompared > 0 ? `, ${uncompared} not compared yet` : ""}. ${AGREEMENT_NOT_ACCURACY}`;
  }

  const accuracy = percent(report.heldOut.accuracy);
  const rows = modelRows(report.model);
  const rubric = report.classifier.rubric.trim();
  return {
    learning: `Learning: ${learning.state.replace(/_/g, " ")}`,
    learningReason: learning.reason,
    cycle: cycleSentence(Math.max(0, Number(learning.refits) || 0), learning.lastChange, timeZone),
    version: learning.version == null ? null : `Version ${learning.version}`,
    agreement: agreementLine,
    agreementNote,
    daysNote: days.length === 0 ? "No days with votes yet."
      : days.length === 1 ? "Only one day so far, so no change over time can be shown yet."
      : comparedDays < 2 ? "Fewer than two days have compared votes, so no change over time can be shown yet."
      : "Agreed of compared votes, by the day the vote was made.",
    days: shown,
    earlierDays: Math.max(0, days.length - shown.length),
    revisions: [...agreement.byClassifierRevision]
      .sort((a, b) => b.classifierRevision.localeCompare(a.classifierRevision, undefined, { numeric: true }))
      .map((entry) => `Classifier revision ${entry.classifierRevision}: ${agreementWords(entry)}`),
    heldOut: accuracy ? `Held-out evaluation: ${accuracy}` : `Held-out evaluation: ${report.heldOut.reason?.trim() || NOT_MEASURED}`,
    counts: [
      `${plural(reviewed, "label")}${labelWords.length ? ` (${labelWords.join(", ")})` : ""}`,
      ...(counts.reviewedDecisions == null ? [] : [`${plural(counts.reviewedDecisions, "reviewed decision")}`]),
      ...(counts.primedExamples ? [`Started with ${plural(counts.primedExamples, "example")}`] : []),
    ],
    awaiting: counts.decisionsAwaitingReview == null ? null
      : `${plural(counts.decisionsAwaitingReview, "decision")} with no label filed in the engine yet. On hosted runs this is only a count of decisions without a label, not a list of work waiting for you.`,
    snapshot,
    question: report.classifier.question,
    classes: report.classifier.classes.join(", "),
    rubric: rubric || null,
    supporting: { rows, reason: rows.length ? null : report.model.reason?.trim() || "No supporting questions have been reported." },
    trimmed: report.trimmed.length ? "Some of this report was left out because it was too large to keep." : null,
  };
}
