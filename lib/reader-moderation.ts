/**
 * The data side of the Administration "Moderation" panel for the reader-steering plugin: rows from the staff-readable
 * models, shaped into a queue, a hidden list and the recent action log. Pure functions, no network: the panel loads the
 * rows and calls the `moderateReader` mutation; everything it shows is decided here so it can be tested.
 */

export type ModerationTarget = "submission" | "comment" | "reader";
export type ModerationActionName = "approve" | "hide" | "unhide" | "ban" | "unban" | "limit" | "promote" | "undo";

export type SubmissionRow = {
  id: string;
  canonicalUrl: string;
  domain: string;
  title: string;
  kind?: string | null;
  note?: string | null;
  readerId: string;
  state: string;
  moderation?: string | null;
  reportCount?: number | null;
  signals?: unknown;
  itemId?: string | null;
  createdAt: string;
};

export type CommentRow = {
  id: string;
  subjectKey: string;
  readerId: string;
  body: string;
  parentId?: string | null;
  state: string;
  moderation?: string | null;
  reportCount?: number | null;
  signals?: unknown;
  createdAt: string;
};

export type ReportRow = { id: string; targetType: string; target: string; reporterReaderId: string; reason: string; state: string; createdAt: string };

export type ActionRow = {
  id: string;
  by: string;
  actorSub: string;
  action: string;
  targetType: string;
  target: string;
  reason?: string | null;
  fromState: string;
  toState: string;
  undoOf?: string | null;
  undoneBy?: string | null;
  at: string;
};

export type Signal = { source: string; policy: string; detector: string; severity: string; excerpt: string };

export type ModerationRow = {
  kind: "submission" | "comment";
  id: string;
  readerId: string;
  handle: string | null;
  createdAt: string;
  state: string;
  title: string;
  url: string | null;
  text: string;
  subject: string | null;
  reports: ReportRow[];
  signals: Signal[];
  canPromote: boolean;
};

export type ActionEntry = ActionRow & { label: string; undoable: boolean; byLabel: string };

const SEVERITY_ORDER: Record<string, number> = { error: 0, warn: 1, info: 2 };

export function parseSignals(value: unknown): Signal[] {
  let parsed: unknown = value;
  if (typeof value === "string") {
    try {
      parsed = JSON.parse(value);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(parsed)) return [];
  return parsed
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map((entry) => ({
      source: String(entry.source ?? ""),
      policy: String(entry.policy ?? ""),
      detector: String(entry.detector ?? ""),
      severity: String(entry.severity ?? "info"),
      excerpt: String(entry.excerpt ?? ""),
    }))
    .sort((left, right) => (SEVERITY_ORDER[left.severity] ?? 3) - (SEVERITY_ORDER[right.severity] ?? 3));
}

/** An address a moderator may follow: http or https only, never `javascript:` or `data:`. */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function newestFirst<T extends { createdAt: string; id: string }>(rows: T[]): T[] {
  return [...rows].sort((left, right) => (left.createdAt === right.createdAt ? right.id.localeCompare(left.id) : right.createdAt.localeCompare(left.createdAt)));
}

function reportsByTarget(reports: ReportRow[]): Map<string, ReportRow[]> {
  const grouped = new Map<string, ReportRow[]>();
  for (const report of reports) {
    if (report.state !== "open") continue;
    grouped.set(report.target, [...(grouped.get(report.target) ?? []), report]);
  }
  return grouped;
}

export function submissionRow(row: SubmissionRow, handles: Record<string, string>, reports: Map<string, ReportRow[]>): ModerationRow {
  return {
    kind: "submission",
    id: row.id,
    readerId: row.readerId,
    handle: handles[row.readerId] ?? null,
    createdAt: row.createdAt,
    state: row.state,
    title: row.title,
    url: safeHttpUrl(row.canonicalUrl),
    text: row.note ?? "",
    subject: row.itemId ?? row.id,
    reports: reports.get(row.id) ?? [],
    signals: parseSignals(row.signals),
    canPromote: row.state === "pending",
  };
}

export function commentRow(row: CommentRow, handles: Record<string, string>, reports: Map<string, ReportRow[]>): ModerationRow {
  return {
    kind: "comment",
    id: row.id,
    readerId: row.readerId,
    handle: handles[row.readerId] ?? null,
    createdAt: row.createdAt,
    state: row.state,
    title: "",
    url: null,
    text: row.body,
    subject: row.subjectKey,
    reports: reports.get(row.id) ?? [],
    signals: parseSignals(row.signals),
    canPromote: false,
  };
}

/** Everything waiting for a decision: new items and reported ones, newest first. Deleted comments are the author's own and are not in it. */
export function buildQueue(input: { submissions: SubmissionRow[]; comments: CommentRow[]; reports: ReportRow[]; handles: Record<string, string> }): ModerationRow[] {
  const reports = reportsByTarget(input.reports);
  const rows = [
    ...input.submissions.filter((row) => (row.moderation ?? "new") === "new").map((row) => submissionRow(row, input.handles, reports)),
    ...input.comments.filter((row) => (row.moderation ?? "new") === "new" && row.state !== "deleted").map((row) => commentRow(row, input.handles, reports)),
  ];
  return newestFirst(rows);
}

/** Items a moderator or a pre-moderation hold keeps out of the public files, newest first, so they can be brought back. */
export function buildHidden(input: { submissions: SubmissionRow[]; comments: CommentRow[]; reports: ReportRow[]; handles: Record<string, string> }): ModerationRow[] {
  const reports = reportsByTarget(input.reports);
  return newestFirst([
    ...input.submissions.filter((row) => row.state === "hidden").map((row) => submissionRow(row, input.handles, reports)),
    ...input.comments.filter((row) => row.state === "hidden").map((row) => commentRow(row, input.handles, reports)),
  ]);
}

const ACTION_LABELS: Record<string, string> = {
  approve: "Approved",
  hide: "Hidden",
  unhide: "Shown again",
  ban: "Banned",
  unban: "Unbanned",
  limit: "Limited",
  promote: "Promoted to a draft",
  undo: "Undid an action",
};

/** The recent log, newest first. An action can be undone while nothing has undone it, and a promotion never. */
export function buildActionLog(actions: ActionRow[], limit = 50): ActionEntry[] {
  return [...actions]
    .sort((left, right) => (left.at === right.at ? right.id.localeCompare(left.id) : right.at.localeCompare(left.at)))
    .slice(0, limit)
    .map((entry) => ({
      ...entry,
      label: ACTION_LABELS[entry.action] ?? entry.action,
      byLabel: entry.by === "ai" ? "AI moderator" : "A moderator",
      undoable: !entry.undoneBy && entry.action !== "promote",
    }));
}

export type Receipt = { status?: string | null; id?: string | null; error?: string | null; message?: string | null };

export function receiptMessage(receipt: Receipt | null | undefined): string {
  if (!receipt) return "The action did not answer. Reload and check.";
  if (receipt.status === "ok") return "Done.";
  return receipt.message || "The action was refused.";
}

export function moderationModeText(mode: unknown): string {
  if (mode === "off") return "Moderation is off for this site: nothing waits in a queue. You can still hide content and ban readers.";
  if (mode === "human") return "New submissions and comments are public at once and wait here for a decision, unless this site holds them until approved.";
  return "Moderation is on.";
}

export function shortReader(readerId: string, handle: string | null): string {
  return handle ? `${handle} (${readerId.slice(0, 8)})` : `reader ${readerId.slice(0, 8)}`;
}
