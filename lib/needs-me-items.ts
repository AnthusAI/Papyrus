/**
 * The adapters that turn what already exists into `NeedsMeItem`s, the one model the "What needs me" feed ranks and renders.
 * Each adapter only reads; deciding is routed back to the existing action for that source (see components/notification-center.tsx).
 *
 *   reference          a pending Reference                          reads the Reference, the Cyclotron's decision on it, its preview
 *   incomplete_capture a pending Reference whose captured text is   reads the same, plus the Reference's capture status (the
 *                      missing or cut off                            `curation` card, else the extracted-text attachments)
 *   capture_needed     an accepted Reference whose content we   reads the Reference (lib/capture-needed.ts reads the star and
 *                      could not collect (not running)          rated partitions), its preview and capture status (the reason)
 *   idea_batch         one batch of generated story ideas            reads the review request and the titles of the ideas it names;
 *                      with an idea still in the Idea column         the ideas are decided on the Stories board, not here
 *   stage_review       an open hard gate or soft review that is      reads the review request (reason, ask, deadline, subject) and the
 *                      not about ideas                               subject story's title and excerpt
 *   flag               an open flag                                  reads the review request
 *   held_email         an email submission held for review           reads the monitoring email summary (subject, sender, verdicts)
 *   link_suggestion    a vector-suggested link between two          reads the suggested relation (its two ends and close match);
 *                      References, or a Reference and a concept     ranked by the close match, most likely first
 *   concept_proposal   a proposed taxonomy concept or reader         STUB: typed, returns nothing until those sources reach the page
 *                      proposal
 */
import type { ReferenceRecord } from "./category-repository";
import { getNewsroomNavHref } from "./newsroom-nav";
import type { MonitoringEmailSummary } from "./monitoring-overview";
import { buildNotificationItems, requestSource, type RequestItem } from "./notification-feed";
import { referenceDisplayTitle, referenceLineageId } from "./newsroom-references";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import { dekAddsInformation, referenceDek, referenceSourceHost, type ReferencePreview } from "./reference-preview";
import { referenceArrivalTime, referenceDisplayTime } from "./reference-feed-ranking";
import { captureReasonWords, type CaptureStatus } from "./reference-capture";
import { starsOf } from "./reference-policy";
import type { RelevanceDecisionView } from "./relevance-decisions";
import { closeMatchText, type RelatedItem } from "./reference-links";
import type { LinkSuggestion } from "./link-suggestions";
import { ideaIdsOf, ideasBoardHref, nextText, type ReviewRequest } from "./review-requests";
import { predictionOf, uncertaintyOf, type NeedsMeCounts, type NeedsMeDecisionState, type NeedsMeItem } from "./needs-me-ranking";

export type NeedsMePayload =
  | { kind: "reference"; reference: ReferenceRecord; lineageId: string; decision: RelevanceDecisionView | undefined; preview: ReferencePreview | undefined; capture: CaptureStatus | undefined; displayTime: number | null }
  | { kind: "ideas"; request: ReviewRequest; ideas: IdeaListing[]; boardHref: string }
  | { kind: "request"; request: ReviewRequest; storyTitle: string | null; excerpt: string | null; storyDeleted: boolean }
  | { kind: "email"; summary: MonitoringEmailSummary }
  | { kind: "concept"; row: ConceptProposalRow }
  | { kind: "link"; suggestion: LinkSuggestion; note: string | null };

/** One idea of a batch, as the card lists it: its title (the id until the title is read) and the stage it is in. */
export type IdeaListing = { id: string; title: string; stage: string | null; href: string };

export type NeedsMeEntry = NeedsMeItem<NeedsMePayload>;

const IDEA_BATCH_DEK = "They wait in the Idea column of the Stories board.";
const ACCEPT_WORD = { accept: "Accept", reject: "Reject" } as const;

function timeOf(value: string | null | undefined): number | null {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

function percent(confidence: number | null): string {
  return confidence === null ? "" : ` ${Math.round(confidence * 100)}%`;
}

// --- references and captures ----------------------------------------------------------------------------------

/**
 * Whether a capture was attempted and came up short, and nobody has said otherwise: text that is thin (too short, or showing signs of
 * being cut off or paywalled), or a curation card that records a failed capture. A Reference nobody has tried to capture yet (the
 * address only, as monitoring discovers it) is not "incomplete": there is nothing to check.
 */
export function captureIsIncomplete(capture: CaptureStatus | undefined): boolean {
  if (!capture || capture.assessment) return false;
  return capture.state === "thin" || (capture.state === "none" && capture.source === "curation");
}

export function referenceDefaultOutcome(decision: RelevanceDecisionView | undefined): string {
  const prediction = predictionOf(decision);
  return prediction
    ? `If you leave it, it stays pending with the Cyclotron's suggestion: ${ACCEPT_WORD[prediction.label]}${percent(prediction.confidence)}.`
    : "If you leave it, it stays pending. Nothing uses it until someone rates it.";
}

export type ReferenceSources = {
  references: ReferenceRecord[];
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined;
  previews: ReadonlyMap<string, ReferencePreview>;
  captures: ReadonlyMap<string, CaptureStatus> | undefined;
  /** Lineage ids rated in this visit: they keep their place showing the answer. */
  visitRated: ReadonlySet<string>;
};

/** Pending References (and the ones rated in this visit), as `reference` items, or `incomplete_capture` when the capture is cut off. */
export function referenceItems(input: ReferenceSources): NeedsMeEntry[] {
  const items: NeedsMeEntry[] = [];
  for (const reference of input.references) {
    const status = normalizeReferenceCurationStatus(reference.curationStatus);
    const lineageId = referenceLineageId(reference);
    if (status === "archived") continue;
    const decided = status === "accepted" || status === "rejected";
    if (decided && !input.visitRated.has(lineageId)) continue;
    const decision = input.decisions?.get(lineageId);
    const preview = input.previews.get(lineageId);
    const capture = input.captures?.get(lineageId);
    const prediction = predictionOf(decision);
    const title = referenceDisplayTitle(reference);
    const dek = referenceDek(reference, preview);
    const host = referenceSourceHost(reference);
    const incomplete = !decided && captureIsIncomplete(capture);
    items.push({
      type: incomplete ? "incomplete_capture" : "reference",
      id: lineageId,
      title,
      dek: incomplete ? "The captured text looks cut off or missing, so the Cyclotron cannot judge it well." : dekAddsInformation(title, dek, preview?.imageUrl ?? null) ? dek : null,
      image: preview?.imageUrl ?? null,
      source: preview?.siteName ?? host ?? "Unknown source",
      host,
      createdAt: referenceArrivalTime(reference) ?? referenceDisplayTime(reference),
      ...(prediction ? { prediction } : {}),
      importance: 1,
      uncertainty: uncertaintyOf(prediction?.pAccept),
      decisionState: status === "accepted" ? "accepted" : status === "rejected" ? "rejected" : "open",
      defaultOutcome: incomplete ? "If you leave it, the Reference stays pending with the text it has." : referenceDefaultOutcome(decision),
      hardGate: false,
      askedForReview: Boolean(decision?.reviewRecommended),
      payload: { kind: "reference", reference, lineageId, decision, preview, capture, displayTime: referenceDisplayTime(reference) },
    });
  }
  return items;
}

// --- accepted References nobody could capture -----------------------------------------------------------------------

export const CAPTURE_NEEDED_WORDS = "We could not collect this. Upload a PDF or paste the text.";

/**
 * Accepted References whose content we could not collect, in the order they were read (stars, then newest; `readCaptureNeeded`). The item is open as a
 * task: the Reference is already accepted, so its Accept shows as given. Ranked by stars within the type (importance 1 + stars, so more stars
 * score higher; the feed's tie-break is newest first); the unstarred follow every starred one. A Reference captured in this visit is not listed.
 */
export function captureNeededItems(input: { references: readonly ReferenceRecord[]; previews: ReadonlyMap<string, ReferencePreview>; captures: ReadonlyMap<string, CaptureStatus> | undefined; capturedNow?: ReadonlySet<string> }): NeedsMeEntry[] {
  const items: NeedsMeEntry[] = [];
  for (const reference of input.references) {
    const lineageId = referenceLineageId(reference);
    if (input.capturedNow?.has(lineageId)) continue;
    const preview = input.previews.get(lineageId);
    const capture = input.captures?.get(lineageId);
    const why = captureReasonWords(capture?.reason);
    const host = referenceSourceHost(reference);
    items.push({
      type: "capture_needed",
      id: `capture#${lineageId}`,
      title: referenceDisplayTitle(reference),
      dek: why ? `${CAPTURE_NEEDED_WORDS} ${why}` : CAPTURE_NEEDED_WORDS,
      image: preview?.imageUrl ?? null,
      source: preview?.siteName ?? host ?? "Unknown source",
      host,
      createdAt: referenceArrivalTime(reference) ?? referenceDisplayTime(reference),
      importance: 1 + starsOf(reference),
      uncertainty: uncertaintyOf(undefined),
      decisionState: "open",
      defaultOutcome: "If you leave it, the Reference stays accepted with only its address. Nothing can be written from its content.",
      hardGate: false,
      askedForReview: true,
      payload: { kind: "reference", reference, lineageId, decision: undefined, preview, capture, displayTime: referenceDisplayTime(reference) },
    });
  }
  return items;
}

// --- idea batches, stories, flags -------------------------------------------------------------------------------------

function choiceState(choice: "accept" | "reject" | null | undefined): NeedsMeDecisionState {
  return choice === "accept" ? "accepted" : choice === "reject" ? "rejected" : "open";
}

/** A batch of generated story ideas: one item that points at the Idea column. It is never decided here, so it has no Accept or Reject. */
export function ideaBatchItem(item: RequestItem, context: { titles: Readonly<Record<string, string>>; stages: Readonly<Record<string, string>>; demo: boolean }): NeedsMeEntry {
  const { request } = item;
  const ideas = ideaIdsOf(request).map((id) => ({
    id, title: context.titles[id] ?? request.links.find((link) => link.id === id)?.label ?? id, stage: context.stages[id] ?? null,
    href: getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(id)}`, context.demo),
  }));
  return {
    type: "idea_batch",
    id: request.id,
    title: request.reason,
    dek: IDEA_BATCH_DEK,
    image: null,
    source: requestSource(request),
    host: null,
    createdAt: timeOf(request.raisedAt),
    importance: 1,
    uncertainty: uncertaintyOf(undefined),
    decisionState: "open",
    defaultOutcome: nextText(request),
    hardGate: false,
    askedForReview: true,
    payload: { kind: "ideas", request, ideas, boardHref: ideasBoardHref(context.demo) },
  };
}

function requestDecisionState(request: ReviewRequest): NeedsMeDecisionState {
  if (request.state === "open") return "open";
  const answer = request.answer;
  if (!answer) return "accepted";
  if (answer.decision === "acknowledge" || (answer.decision === "approve" && request.mode === "flag")) return "acknowledged";
  if (answer.decision === "reject" || (answer.decision === "feedback" && answer.steer === "not_this_kind")) return "rejected";
  return "accepted";
}

export function requestItem(
  item: RequestItem,
  context: { titles: Readonly<Record<string, string>>; excerpts: Readonly<Record<string, string>>; deleted: ReadonlySet<string> },
): NeedsMeEntry {
  const { request } = item;
  const storyId = request.subject.type === "story" ? request.subject.id : null;
  const flag = request.mode === "flag";
  return {
    type: flag ? "flag" : "stage_review",
    id: request.id,
    title: request.reason,
    dek: request.ask,
    image: null,
    source: requestSource(request),
    host: null,
    createdAt: timeOf(request.raisedAt),
    importance: 1,
    uncertainty: uncertaintyOf(undefined),
    decisionState: requestDecisionState(request),
    defaultOutcome: nextText(request),
    hardGate: request.mode === "hard_gate",
    askedForReview: true,
    payload: {
      kind: "request",
      request,
      storyTitle: storyId ? context.titles[storyId] ?? null : null,
      excerpt: storyId ? context.excerpts[storyId] ?? null : null,
      storyDeleted: storyId ? context.deleted.has(storyId) : false,
    },
  };
}

// --- held email --------------------------------------------------------------------------------------------------

function senderDomain(summary: MonitoringEmailSummary): string | null {
  const from = summary.headerFrom || summary.envelopeSender || "";
  const address = from.match(/@([A-Za-z0-9.-]+\.[A-Za-z]{2,})/);
  return address ? address[1].toLowerCase() : null;
}

/** The decision recorded on a receipt, else the one made in this visit. */
export function emailDecisionState(summary: MonitoringEmailSummary, decided: ReadonlyMap<string, "accept" | "reject">): NeedsMeDecisionState {
  const made = decided.get(summary.receiptId) ?? summary.quarantine?.decision?.action;
  return choiceState(made);
}

/** Held email submissions: untrusted, so only the subject and sender facts are used; the body is read in the detail pane as inert text. */
export function heldEmailItems(summaries: readonly MonitoringEmailSummary[], decided: ReadonlyMap<string, "accept" | "reject">): NeedsMeEntry[] {
  const items: NeedsMeEntry[] = [];
  for (const summary of summaries) {
    const held = summary.quarantine?.state === "quarantined";
    const decision = emailDecisionState(summary, decided);
    if (!held && !decided.has(summary.receiptId)) continue;
    const domain = senderDomain(summary);
    items.push({
      type: "held_email",
      id: `email#${summary.receiptId}`,
      title: summary.subject?.trim() || "(no subject)",
      dek: summary.warnings.length ? `Held for review: ${summary.warnings.join(", ")}.` : `Held for review. ${summary.linkCount} candidate ${summary.linkCount === 1 ? "link" : "links"}.`,
      image: null,
      source: domain ?? "Email submission",
      host: domain,
      createdAt: timeOf(summary.observedAt),
      importance: 1,
      uncertainty: uncertaintyOf(undefined),
      decisionState: decision,
      defaultOutcome: "If you leave it, it stays held privately. Nothing is routed from it unless you accept it.",
      hardGate: false,
      askedForReview: true,
      payload: { kind: "email", summary },
    });
  }
  return items;
}

// --- link suggestions --------------------------------------------------------------------------------------------

/** What a link end is called on a card: a Reference by its title, a concept by its hashtag. */
export function linkEndName(item: RelatedItem): string {
  return item.kind === "concept" ? item.hashtag ?? item.title : item.title;
}

export type LinkDecision = { choice: "accept" | "reject"; note: string };

/**
 * Suggested links, as items. They are ranked by their close match (the importance), most likely first; the vector index records no
 * probability, so there is no prediction and a suggestion is never decided automatically. A suggestion decided in this visit keeps its
 * place showing the answer, like a rated Reference.
 */
export function linkSuggestionItems(suggestions: readonly LinkSuggestion[], decided: ReadonlyMap<string, LinkDecision>): NeedsMeEntry[] {
  return suggestions.map((suggestion) => {
    const made = decided.get(suggestion.relationId);
    const match = closeMatchText(suggestion.similarity);
    const concept = suggestion.object.kind === "concept";
    return {
      type: "link_suggestion",
      id: `link#${suggestion.relationId}`,
      title: `${linkEndName(suggestion.subject)} and ${linkEndName(suggestion.object)}`,
      dek: `${concept ? "A Reference and a concept" : "Two References"} that look like they belong together${match ? `: ${match}` : ""}.`,
      image: null,
      source: "Suggested link",
      host: suggestion.subject.host,
      createdAt: timeOf(suggestion.createdAt),
      importance: suggestion.similarity ?? 0,
      uncertainty: uncertaintyOf(undefined),
      decisionState: choiceState(made?.choice),
      defaultOutcome: "If you leave it, the link is not made and the suggestion keeps waiting.",
      hardGate: false,
      askedForReview: true,
      payload: { kind: "link", suggestion, note: made?.note ?? null },
    } satisfies NeedsMeEntry;
  });
}

// --- stubs ---------------------------------------------------------------------------------------------------------

/** A proposed taxonomy concept or a reader's proposal. Not on the page yet: the source is typed so the adapter has a place to land. */
export type ConceptProposalRow = { id: string; title: string; summary: string | null; proposedBy: "cyclotron" | "reader"; createdAt: string | null };

export function conceptProposalItems(_rows: readonly ConceptProposalRow[]): NeedsMeEntry[] {
  return [];
}

// --- all of it -----------------------------------------------------------------------------------------------------

export type NeedsMeSources = ReferenceSources & {
  /** Accepted References that need a person to capture them, already ordered and limited (`readCaptureNeeded`). */
  captureNeeded?: readonly ReferenceRecord[];
  /** Lineage ids a person captured in this visit: they leave the list. */
  capturedNow?: ReadonlySet<string>;
  requests: ReviewRequest[];
  /** Request ids kept on screen in this visit. */
  stay: ReadonlySet<string>;
  demo?: boolean;
  /** The stage of each idea named by an open batch, by lineage id, once read. */
  ideaStages?: Readonly<Record<string, string>>;
  storyTitles: Readonly<Record<string, string>>;
  storyExcerpts: Readonly<Record<string, string>>;
  deletedStories: ReadonlySet<string>;
  emails: readonly MonitoringEmailSummary[];
  emailsDecided: ReadonlyMap<string, "accept" | "reject">;
  concepts?: readonly ConceptProposalRow[];
  /** The suggested links read so far (a page at a time), and the ones decided in this visit by relation id. */
  linkSuggestions?: readonly LinkSuggestion[];
  linksDecided?: ReadonlyMap<string, LinkDecision>;
};

/** Every source, as one list of items (unordered: `rankNeedsMe` orders it). */
export function buildNeedsMeItems(sources: NeedsMeSources): NeedsMeEntry[] {
  const fromRequests = buildNotificationItems({ requests: sources.requests, ideaStages: sources.ideaStages, stay: sources.stay });
  const context = { titles: sources.storyTitles, excerpts: sources.storyExcerpts, deleted: sources.deletedStories };
  const ideaContext = { titles: sources.storyTitles, stages: sources.ideaStages ?? {}, demo: Boolean(sources.demo) };
  return [
    ...referenceItems(sources),
    ...captureNeededItems({ references: sources.captureNeeded ?? [], previews: sources.previews, captures: sources.captures, capturedNow: sources.capturedNow }),
    ...fromRequests.ideas.map((item) => ideaBatchItem(item, ideaContext)),
    ...fromRequests.reviews.map((item) => requestItem(item, context)),
    ...fromRequests.flags.map((item) => requestItem(item, context)),
    ...heldEmailItems(sources.emails, sources.emailsDecided),
    ...linkSuggestionItems(sources.linkSuggestions ?? [], sources.linksDecided ?? new Map()),
    ...conceptProposalItems(sources.concepts ?? []),
  ];
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "2 idea batches and 12 references waiting for you"; "All caught up" when nothing waits. */
export function waitingTextFor(counts: NeedsMeCounts): string {
  const parts = [
    counts.ideas ? plural(counts.ideas, "idea batch", "idea batches") : null,
    counts.references ? plural(counts.references, "reference") : null,
    counts.stories ? plural(counts.stories, "story review") : null,
    counts.email ? plural(counts.email, "held email", "held emails") : null,
    counts.captures ? plural(counts.captures, "capture to check", "captures to check") : null,
    counts.tocapture ? plural(counts.tocapture, "reference to capture", "references to capture") : null,
    counts.links ? plural(counts.links, "link suggestion") : null,
    counts.other ? plural(counts.other, "other item") : null,
  ].filter((part): part is string => part !== null);
  if (!parts.length) return "All caught up";
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `${list} waiting for you`;
}
