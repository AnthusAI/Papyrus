/**
 * The AI drafts inside a review request (a trend or monitor story batch, an idea batch): what each one says, what it rests on,
 * and how an editor's Accept or Reject on it moves the Proposal and, once every draft is decided, closes the request.
 * Pure functions, no network, so the card and its tests share them.
 */
import { proposalHref, draftIdsOf, type AnswerInput, type DraftDecision, type ReviewLink, type ReviewRequest } from "./review-requests";

/** A Proposal row as the console reads it; JSON fields may arrive as strings. */
export type DraftRow = {
  id: string;
  kind: string;
  title: string;
  summary?: string | null;
  body?: string | null;
  state: string;
  held?: boolean | null;
  evidence?: unknown;
  history?: unknown;
  override?: unknown;
  createdAt?: string | null;
};

export type DraftSource = { title: string; date: string | null; url: string | null };
export type DraftChoice = "accept" | "reject";

export type DraftView = {
  id: string;
  kindLabel: string;
  headline: string;
  dek: string | null;
  /** The draft's own words: the body without its Sources and Signals lists (those are shown as chips) or its closing "Section:" line. */
  bodyText: string;
  section: string | null;
  /** The evidence in words: the signals it rests on, or the monitor that found its source. */
  evidence: string[];
  sources: DraftSource[];
  moreSources: number;
  state: string;
  held: boolean;
  href: string;
  /** What the Proposal's own state says an editor already decided, or null while it is open. */
  decided: DraftChoice | null;
};

export const MAXIMUM_SOURCES = 5;
const MAXIMUM_EVIDENCE = 3;
const KIND_WORDS: Record<string, string> = { story_draft: "Story draft", new_concept: "New concept", rename: "Rename", merge: "Merge", split: "Split", new_column: "New column", element_symbol: "Element symbol" };

/** JSON fields arrive as strings, and a field written through `JSON.stringify` of a string arrives encoded twice: unwrap until it is not text. */
function parseJson(value: unknown, depth = 0): unknown {
  if (typeof value !== "string") return value ?? null;
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "string" && depth < 2 ? parseJson(parsed, depth + 1) : parsed;
  } catch {
    return null;
  }
}

/** The lines of a "## Heading" section of the body, up to the next heading or the closing "Section:" line. */
function bodySection(body: string, heading: RegExp): string[] {
  const lines = body.split(/\r?\n/);
  const start = lines.findIndex((line) => heading.test(line.trim()));
  if (start < 0) return [];
  const found: string[] = [];
  for (const line of lines.slice(start + 1)) {
    const text = line.trim();
    if (/^#{1,6}\s/.test(text) || /^Section:/.test(text)) break;
    if (text) found.push(text);
  }
  return found;
}

export function parseSource(line: string): DraftSource | null {
  const numbered = line.match(/^\d+\.\s+(.+)$/);
  if (!numbered) return null;
  let rest = numbered[1].trim();
  let url: string | null = null;
  const link = rest.match(/^(.*?)\s*(https?:\/\/\S+)$/);
  if (link) {
    rest = link[1].trim();
    url = link[2];
  }
  let date: string | null = null;
  const dated = rest.match(/^(.*?)\s*\((\d{4}-\d{2}-\d{2})\)$/);
  if (dated) {
    rest = dated[1].trim();
    date = dated[2];
  }
  return rest ? { title: rest, date, url } : null;
}

function evidenceLines(row: DraftRow): string[] {
  const body = row.body ?? "";
  const signals = bodySection(body, /^##\s+Signals cited\s*$/i)
    .map((line) => line.match(/^\d+\.\s+(.+?)(?:\s+\(https?:\/\/[^)\s]*\))?\s*(?:`[^`]*`)?\s*$/)?.[1]?.trim())
    .filter((line): line is string => Boolean(line));
  if (signals.length) return signals.slice(0, MAXIMUM_EVIDENCE);
  const evidence = parseJson(row.evidence);
  const source = evidence && typeof evidence === "object" && typeof (evidence as { source?: unknown }).source === "string" ? String((evidence as { source: string }).source) : "";
  if (!source) return [];
  const monitor = source.match(/^(.+?) monitor:/);
  const lines = [monitor ? `Found by the ${monitor[1]} monitor.` : source];
  const check = body.match(/relevance check labelled it (\w+) with a score of (\d+(?:\.\d+)?)\./i);
  if (check) lines.push(`Relevance check: ${check[1]}, score ${check[2]}.`);
  return lines;
}

/** The prose of a draft: every line except the Sources and Signals cited lists and the closing "Section: ..." line. */
export function draftBodyText(body: string): string {
  const kept: string[] = [];
  let skipping = false;
  for (const line of body.split(/\r?\n/)) {
    const text = line.trim();
    if (/^#{1,6}\s/.test(text)) skipping = /^##\s+(Sources?|Signals cited)\s*$/i.test(text);
    if (skipping || /^Section:\s.*Drafted by AI/i.test(text)) continue;
    kept.push(line);
  }
  return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function draftChoiceOf(state: string): DraftChoice | null {
  return state === "approved" ? "accept" : state === "declined" ? "reject" : null;
}

/** What an editor reads before deciding: headline, dek, section, evidence and the cited sources, from the Proposal row. */
export function draftView(row: DraftRow, demo = false): DraftView {
  const body = row.body ?? "";
  const sources = [...bodySection(body, /^##\s+Sources?\s*$/i)].map(parseSource).filter((source): source is DraftSource => source !== null);
  const section = body.match(/^Section:\s*(.+?)\.\s+Drafted by AI/m)?.[1]?.trim() ?? null;
  const override = parseJson(row.override) as { result?: string } | null;
  return {
    id: row.id,
    kindLabel: KIND_WORDS[row.kind] ?? row.kind,
    headline: row.title,
    dek: row.summary?.trim() || null,
    bodyText: draftBodyText(body),
    section,
    evidence: evidenceLines(row),
    sources: sources.slice(0, MAXIMUM_SOURCES),
    moreSources: Math.max(0, sources.length - MAXIMUM_SOURCES),
    state: row.state,
    held: Boolean(row.held),
    href: proposalHref(row.id, demo),
    decided: draftChoiceOf(row.state) ?? (row.state === "overridden_by_editor" ? (override?.result === "declined" ? "reject" : "accept") : null),
  };
}

// --- moving the Proposal ----------------------------------------------------------------------------------------

/**
 * The states Accept walks through, one `transitionProposal` call each, ending at "approved" (the same state the Proposals panel's Approve reaches).
 * A draft goes through steering and editor review on the way, as the panel's own "Move to editor review" then "Approve" do.
 */
export function acceptPath(state: string): string[] | null {
  if (state === "draft") return ["in_steering", "editor_review", "approved"];
  if (state === "in_steering") return ["editor_review", "approved"];
  if (state === "editor_review") return ["approved"];
  return null;
}

/** Reject ends at "declined". */
export function rejectPath(state: string): string[] | null {
  if (state === "draft") return ["declined"];
  if (state === "in_steering") return ["editor_review", "declined"];
  if (state === "editor_review") return ["declined"];
  return null;
}

/** The sentence for a draft that cannot move, or null when it can. A hold is named, never hidden. */
export function cannotMoveReason(view: Pick<DraftView, "state" | "held" | "decided">): string | null {
  if (view.decided) return null;
  if (view.held) return "This draft is on hold in Proposals. Release the hold there before you decide it.";
  return null;
}

// --- the request's answer ---------------------------------------------------------------------------------------

export type DraftLookup = Readonly<Record<string, DraftView | undefined>>;

/** The decision recorded on a link, else what the Proposal's own state says (decided in Proposals), else null. */
export function draftDecisionOf(link: ReviewLink | undefined, view: DraftView | undefined, fallback: { by: string; at: string }): DraftDecision | null {
  if (link?.decision) return link.decision;
  return view?.decided ? { choice: view.decided, title: view.headline, why: null, notThisKind: false, ...fallback } : null;
}

/** Ids of the request's drafts that exist and are not decided yet. */
export function undecidedDraftIds(request: ReviewRequest, drafts: DraftLookup): string[] {
  return draftIdsOf(request).filter((id) => {
    const view = drafts[id];
    if (!view) return false;
    return draftDecisionOf(request.links.find((link) => link.id === id), view, { by: "", at: "" }) === null;
  });
}

/** How many drafts in these requests still wait for a decision (drafts not yet loaded count as waiting). */
export function draftsToDecide(requests: ReviewRequest[], drafts: DraftLookup, missing: ReadonlySet<string> = new Set()): number {
  return requests.reduce((total, request) => total + draftIdsOf(request).filter((id) => !missing.has(id) && (!drafts[id] || undecidedDraftIds(request, drafts).includes(id))).length, 0);
}

/** The links with one draft's decision recorded. Links for drafts the request did not name are not invented. */
export function withDecision(request: ReviewRequest, draftId: string, decision: DraftDecision): ReviewLink[] {
  const named = request.links.some((link) => link.id === draftId);
  const links = named ? request.links : [...request.links, { type: "proposal", id: draftId }];
  return links.map((link) => (link.id === draftId ? { ...link, decision } : link));
}

/** The update that records a decision on one draft while the request stays open. Applied with the condition state = open. */
export function draftDecisionUpdate(request: ReviewRequest, draftId: string, decision: DraftDecision): Record<string, unknown> {
  const history = [...request.history, { at: decision.at, event: "draft_decided", by: decision.by, note: `${decision.choice} ${draftId}` }].slice(-50);
  return { id: request.id, links: JSON.stringify(withDecision(request, draftId, decision)), updatedAt: decision.at, history: JSON.stringify(history) };
}

function quote(text: string): string {
  return `"${text.replace(/"/g, "'")}"`;
}

/** The words of an answer that covers several drafts: each rejection and each Why in a sentence, the plain Accepts of a mixed batch in one more. */
export function draftFeedback(decisions: readonly (DraftDecision & { id: string })[]): string | null {
  const rejected = decisions.filter((decision) => decision.choice === "reject");
  const lines = decisions
    .filter((decision) => decision.choice === "reject" || decision.why)
    .map((decision) => `${decision.choice === "accept" ? "Accepted" : "Rejected"} ${quote(decision.title ?? decision.id)}${decision.notThisKind ? " as not this kind of story" : ""}${decision.why ? `: ${decision.why}` : ""}.`);
  if (rejected.length > 0 && rejected.length < decisions.length) {
    const kept = decisions.filter((decision) => decision.choice === "accept" && !decision.why).map((decision) => quote(decision.title ?? decision.id));
    if (kept.length) lines.push(`Accepted ${kept.join(", ")}.`);
  }
  return lines.join(" ") || null;
}

/**
 * The update that changes only the Why of a draft that is already decided. The Why is stored where the decision is: on the request's link
 * for the draft and, once the request has closed, in its answer (`drafts` and the `feedback` sentence the idea pipeline reads back).
 * The choice, the steering chip, who decided and when stay as they were. Applied with the condition that the state is unchanged.
 */
export function draftReasonUpdate(request: ReviewRequest, draftId: string, decision: DraftDecision, editor: string, now: Date): Record<string, unknown> {
  const at = now.toISOString();
  const why = decision.why?.trim() || null;
  const next: DraftDecision = { ...decision, why };
  const history = [...request.history, { at, event: "reason_edited", by: editor, note: `${decision.choice} ${draftId}` }].slice(-50);
  const update: Record<string, unknown> = { id: request.id, links: JSON.stringify(withDecision(request, draftId, next)), updatedAt: at, history: JSON.stringify(history) };
  if (request.answer?.drafts?.length && request.state === "answered") {
    const known = request.answer.drafts;
    const drafts = known.some((entry) => entry.id === draftId) ? known.map((entry) => (entry.id === draftId ? { ...entry, why } : entry)) : [...known, { ...next, id: draftId }];
    update.answer = JSON.stringify({ ...request.answer, drafts, feedback: draftFeedback(drafts) });
  }
  return update;
}

/**
 * The answer that closes a request once every draft that can be decided has been: Accept on all is an approval, Reject on all a rejection,
 * a mix is an answer with a note naming each draft. A draft rejected as the wrong kind of story makes the answer a "not this kind" steer, which
 * the idea pipeline reads back. Null while a draft is undecided, or when no draft of the request could be loaded.
 */
export function batchAnswer(request: ReviewRequest, drafts: DraftLookup, fallback: { by: string; at: string }): AnswerInput | null {
  const ids = draftIdsOf(request).filter((id) => drafts[id]);
  if (!ids.length) return null;
  const decisions: (DraftDecision & { id: string })[] = [];
  for (const id of ids) {
    const decision = draftDecisionOf(request.links.find((link) => link.id === id), drafts[id], fallback);
    if (!decision) return null;
    decisions.push({ ...decision, title: decision.title ?? drafts[id]?.headline, id });
  }
  const rejected = decisions.filter((decision) => decision.choice === "reject");
  const mixed = rejected.length > 0 && rejected.length < decisions.length;
  const links = request.links.some((link) => link.type === "proposal") ? request.links.map((link) => {
    const decision = decisions.find((entry) => entry.id === link.id);
    return decision ? { ...link, decision } : link;
  }) : [...request.links, ...decisions.map((decision) => ({ type: "proposal", id: decision.id, decision }))];
  return {
    decision: !rejected.length ? "approve" : mixed ? "feedback" : "reject",
    feedback: draftFeedback(decisions),
    steer: rejected.some((decision) => decision.notThisKind) ? "not_this_kind" : null,
    drafts: decisions,
    links,
  };
}
