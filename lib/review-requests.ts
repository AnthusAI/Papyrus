/**
 * The Notification Center's model (PPY-1cd261, PPY-ab6a50): review requests, the Cyclotron items that wait for a person,
 * the auto-decided stream, and the words the page says about each. Pure functions only, so the page and its tests share them.
 *
 * Principle (docs/notification-center.md): everything except a hard gate keeps moving if nobody acts. Each entry says in words
 * what happens next without the reader, and only a hard gate says "Waiting for you".
 */
import type { ReferenceRecord } from "./category-repository";
import { getNewsroomNavHref } from "./newsroom-nav";
import { referenceDisplayTitle, referenceLineageId } from "./newsroom-references";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import type { RelevanceDecisionView } from "./relevance-decisions";

export type ReviewMode = "flag" | "soft_review" | "hard_gate";
export type ReviewState = "open" | "answered" | "timed_out" | "withdrawn";
export type ReviewDecision = "approve" | "reject" | "feedback";
export type ReviewSteer = "adjust" | "not_this_kind";

export type ReviewAnswer = { decision: ReviewDecision; feedback: string | null; steer: ReviewSteer | null; by: string; at: string };
export type ReviewHistoryEntry = { at: string; event: string; by?: string; note?: string };
export type ReviewLink = { label?: string; url?: string; type?: string; id?: string };

export type ReviewRequest = {
  id: string;
  subject: { type: string; id: string };
  mode: ReviewMode;
  reason: string;
  ask: string | null;
  raisedBy: string;
  raisedAt: string;
  deadline: string | null;
  state: ReviewState;
  answer: ReviewAnswer | null;
  links: ReviewLink[];
  history: ReviewHistoryEntry[];
  appliedIn: { runId: string; by: string; at: string; note?: string | null } | null;
  updatedAt: string;
};

export const PROCEEDED_WITHOUT_REVIEW = "proceeded without review";
const MAX_HISTORY = 50;

function parseJson<T>(value: unknown, fallback: T): T {
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as T;
    } catch {
      return fallback;
    }
  }
  return value === null || value === undefined ? fallback : (value as T);
}

/** A row from the API (JSON fields arrive as strings) as a request. */
export function normalizeReviewRow(row: Record<string, unknown>): ReviewRequest {
  return {
    id: String(row.id),
    subject: parseJson(row.subject, { type: "unknown", id: "" }),
    mode: row.mode as ReviewMode,
    reason: String(row.reason ?? ""),
    ask: typeof row.ask === "string" ? row.ask : null,
    raisedBy: String(row.raisedBy ?? ""),
    raisedAt: String(row.raisedAt ?? ""),
    deadline: typeof row.deadline === "string" ? row.deadline : null,
    state: row.state as ReviewState,
    answer: parseJson<ReviewAnswer | null>(row.answer, null),
    links: parseJson<ReviewLink[]>(row.links, []),
    history: parseJson<ReviewHistoryEntry[]>(row.history, []),
    appliedIn: parseJson(row.appliedIn, null),
    updatedAt: String(row.updatedAt ?? row.raisedAt ?? ""),
  };
}

// --- the deadline (checked on read) ---------------------------------------------------------------------

export function isDue(request: ReviewRequest, now: Date): boolean {
  return request.mode === "soft_review" && request.state === "open" && request.deadline !== null && new Date(request.deadline).getTime() <= now.getTime();
}

/** The update that marks a due soft review as timed out, "proceeded without review". Applied with the condition state = open. */
export function timeoutUpdate(request: ReviewRequest, now: Date): Record<string, unknown> {
  const at = now.toISOString();
  const history = [...request.history, { at, event: "timed_out", by: "system", note: PROCEEDED_WITHOUT_REVIEW }].slice(-MAX_HISTORY);
  return { id: request.id, state: "timed_out", updatedAt: at, history: JSON.stringify(history) };
}

export type AnswerInput = { decision: ReviewDecision; feedback?: string | null; steer?: ReviewSteer | null };

/** The update for an answer, or an Error saying why it is refused. Applied with the condition state = open. */
export function answerUpdate(request: ReviewRequest, input: AnswerInput, by: string, now: Date): Record<string, unknown> {
  if (request.state !== "open") throw new Error(`This request is ${request.state.replace("_", " ")}${request.state === "timed_out" ? ` (${PROCEEDED_WITHOUT_REVIEW})` : ""} and can no longer be answered.`);
  const feedback = input.feedback?.trim() || null;
  const steer = input.steer ?? null;
  if (input.decision === "feedback" && !feedback && !steer) throw new Error("Write a note, or choose \"Not this kind of thing\".");
  const at = now.toISOString();
  const answer: ReviewAnswer = { decision: input.decision, feedback, steer, by, at };
  const history = [...request.history, { at, event: "answered", by, note: input.decision }].slice(-MAX_HISTORY);
  return { id: request.id, state: "answered", answer: JSON.stringify(answer), updatedAt: at, history: JSON.stringify(history) };
}

// --- words ------------------------------------------------------------------------------------------------

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.toISOString().slice(0, 10)} ${date.toISOString().slice(11, 16)} UTC`;
}

export function modeLabel(mode: ReviewMode): string {
  return mode === "hard_gate" ? "Hard gate" : mode === "soft_review" ? "Soft review" : "Flag";
}

/** A mark and the words, never colour alone. */
export function modeMark(mode: ReviewMode): string {
  return mode === "hard_gate" ? "■" : mode === "soft_review" ? "◐" : "⚑";
}

/** What happens next without the reader. Only a hard gate says "Waiting for you". */
export function nextText(request: ReviewRequest): string {
  if (request.state === "open") {
    if (request.mode === "hard_gate") return "Waiting for you. Nothing continues until you approve or reject.";
    if (request.mode === "soft_review") return `Proceeds automatically on ${formatWhen(request.deadline)} unless you steer it.`;
    return "Nothing is waiting on this. It stays here until you acknowledge it.";
  }
  if (request.state === "timed_out") return `Proceeded without review on ${formatWhen(request.updatedAt)}.`;
  if (request.state === "withdrawn") return "Withdrawn by the step that raised it.";
  const answer = request.answer;
  return answer ? `${answerWords(answer)} by ${answer.by} on ${formatWhen(answer.at)}.` : "Answered.";
}

export function answerWords(answer: ReviewAnswer): string {
  if (answer.steer === "not_this_kind") return "Steered: not this kind of thing";
  if (answer.decision === "approve") return "Approved";
  if (answer.decision === "reject") return "Rejected";
  return "Steered with a note";
}

/** "You steered X, applied in run Y": what became of a person's input. */
export function steeringText(request: ReviewRequest): string | null {
  const answer = request.answer;
  if (request.state !== "answered" || !answer || !(answer.feedback || answer.steer || answer.decision === "reject")) return null;
  const said = answer.feedback ? `"${answer.feedback}"` : answerWords(answer).toLowerCase();
  if (request.appliedIn) return `You steered ${said}. Applied in run ${request.appliedIn.runId} on ${formatWhen(request.appliedIn.at)}.`;
  return `You steered ${said}. ${request.raisedBy} has not used it yet; it will on its next run.`;
}

export function subjectHref(subject: { type: string; id: string }, demo = false): string | null {
  const id = encodeURIComponent(subject.id);
  if (subject.type === "story") return getNewsroomNavHref(`/newsroom/articles/${id}`, demo);
  if (subject.type === "reference" || subject.type === "cyclotron_decision") return getNewsroomNavHref(`/newsroom/references/${id}`, demo);
  if (subject.type === "proposal") return getNewsroomNavHref(`/newsroom/topics?proposal=${id}`, demo);
  if (subject.type === "automation_run") return getNewsroomNavHref("/newsroom/administration/automations", demo);
  return null;
}

// --- Cyclotron items ---------------------------------------------------------------------------------------

export type CyclotronEntry = {
  lineageId: string;
  title: string;
  label: string;
  confidence: number | null;
  decidedAt: string | null;
  reviewDetail: string | null;
  reviewedByPerson: boolean;
  href: string;
};

function cyclotronEntry(reference: ReferenceRecord, decision: RelevanceDecisionView, reviewed: ReadonlySet<string>, demo: boolean): CyclotronEntry {
  const lineageId = referenceLineageId(reference);
  return {
    lineageId, title: referenceDisplayTitle(reference), label: decision.label, confidence: decision.confidence,
    decidedAt: decision.decidedAt, reviewDetail: decision.reviewDetail, reviewedByPerson: reviewed.has(lineageId),
    href: getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo),
  };
}

/** Items the Cyclotron routed to a person (the References tab's own rule: review recommended and still pending). Least confident first. */
export function cyclotronHeldForReview(references: ReferenceRecord[], decisions: ReadonlyMap<string, RelevanceDecisionView>, demo = false): CyclotronEntry[] {
  const entries: CyclotronEntry[] = [];
  for (const reference of references) {
    const decision = decisions.get(referenceLineageId(reference));
    if (decision?.reviewRecommended && normalizeReferenceCurationStatus(reference.curationStatus) === "pending") {
      entries.push(cyclotronEntry(reference, decision, new Set(), demo));
    }
  }
  return entries.sort((a, b) => (a.confidence ?? 1) - (b.confidence ?? 1));
}

/** Recent classifications the Cyclotron made on its own confidence. Read only here; correcting happens on the reference. Newest first. */
export function cyclotronAutoDecided(references: ReferenceRecord[], decisions: ReadonlyMap<string, RelevanceDecisionView>, reviewed: ReadonlySet<string>, demo = false, limit = 20): CyclotronEntry[] {
  const entries: CyclotronEntry[] = [];
  for (const reference of references) {
    const decision = decisions.get(referenceLineageId(reference));
    if (decision && !decision.reviewRecommended) entries.push(cyclotronEntry(reference, decision, reviewed, demo));
  }
  return entries.sort((a, b) => (b.decidedAt ?? "").localeCompare(a.decidedAt ?? "")).slice(0, limit);
}

// --- the page's shape -------------------------------------------------------------------------------------------

export type NotificationSections = {
  hardGates: ReviewRequest[];
  softReviews: ReviewRequest[];
  flags: ReviewRequest[];
  /** Answered, timed out or withdrawn, newest first: what people said and what became of it. */
  decided: ReviewRequest[];
};

export function sectionReviews(requests: ReviewRequest[]): NotificationSections {
  const open = requests.filter((request) => request.state === "open");
  const byRaised = (a: ReviewRequest, b: ReviewRequest) => a.raisedAt.localeCompare(b.raisedAt);
  return {
    hardGates: open.filter((request) => request.mode === "hard_gate").sort(byRaised),
    softReviews: open.filter((request) => request.mode === "soft_review").sort((a, b) => (a.deadline ?? "").localeCompare(b.deadline ?? "")),
    flags: open.filter((request) => request.mode === "flag").sort((a, b) => b.raisedAt.localeCompare(a.raisedAt)),
    decided: requests.filter((request) => request.state !== "open").sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
  };
}

export type NotificationSummary = { waiting: number; proceedingSoon: number; decidedBySystem: number; unread: number };

/**
 * "N waiting for you · N proceeding soon · N recently decided by the system".
 * Waiting = hard gates plus Cyclotron items held for review (both stay put until a person acts). Proceeding soon = open soft reviews.
 */
export function summarize(sections: NotificationSections, held: CyclotronEntry[], autoDecided: CyclotronEntry[], unread: number): NotificationSummary {
  return { waiting: sections.hardGates.length + held.length, proceedingSoon: sections.softReviews.length, decidedBySystem: autoDecided.length, unread };
}

export function summaryText(summary: NotificationSummary): string {
  return `${summary.waiting} waiting for you · ${summary.proceedingSoon} proceeding soon · ${summary.decidedBySystem} recently decided by the system`;
}

export function isUnread(request: ReviewRequest, readIds: ReadonlySet<string>): boolean {
  return !readIds.has(request.id);
}
