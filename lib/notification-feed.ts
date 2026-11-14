/**
 * The Notification Center as a feed of cards ("What needs me?"): which cards there are, how they are counted, filtered and
 * worded. Pure functions, so the page and its tests share them. A batch of generated story ideas is ONE card that links to the Idea
 * column of the Stories board: the ideas are decided there (forward = accept, spiked with a reason = decline), not in the card.
 */
import type { ReferenceRecord } from "./category-repository";
import { referenceDisplayTitle, referenceLineageId } from "./newsroom-references";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import { ideaIdsOf, isIdeaBatch, sectionReviews, type ReviewRequest } from "./review-requests";
import { getNewsroomNavHref } from "./newsroom-nav";

/** A request that is decided as a whole: a hard gate, a soft review of something that is not a batch of ideas, or a flag. */
export type RequestItem = { kind: "request"; key: string; request: ReviewRequest };

export type NotificationItems = {
  /** Batches of generated story ideas that still have an idea in the Idea column. */
  ideas: RequestItem[];
  /** Hard gates first, then the other soft reviews, soonest deadline first. */
  reviews: RequestItem[];
  /** For your information: flags. */
  flags: RequestItem[];
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

/** "Oct 27", in UTC so the words do not change with the reader's time zone. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
}

function sentenceCase(slug: string): string {
  const spaced = slug.replace(/[-_.]+/g, " ").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : "";
}

/** Where a request came from, in words: the run its batch names ("Monitor stories run"), else the step that raised it. */
export function requestSource(request: Pick<ReviewRequest, "subject" | "raisedBy">): string {
  if (request.subject.type === "batch") {
    const named = request.subject.id.replace(/-\d{8}t\d{6}z.*$/i, "").replace(/-[0-9a-f]{6,}$/i, "");
    if (/[a-z]{3,}/i.test(named)) return sentenceCase(named);
  }
  return sentenceCase(request.raisedBy) || "An automated step";
}

/** The small caption on a card that came out of a request: "from Monitor stories run · Oct 27". */
export function requestCaption(request: Pick<ReviewRequest, "subject" | "raisedBy" | "raisedAt">): string {
  const when = shortDate(request.raisedAt);
  return `from ${requestSource(request)}${when ? ` · ${when}` : ""}`;
}

/** The stage key of the Idea column. */
export const IDEA_STAGE = "idea";

/** Whether a batch still has an idea waiting in the Idea column. Ideas whose stage is not known yet count as waiting, so a card never disappears on a slow read. */
export function batchHasIdeasWaiting(request: Pick<ReviewRequest, "links">, stages: Readonly<Record<string, string>>): boolean {
  return ideaIdsOf(request).some((id) => (stages[id] ?? IDEA_STAGE) === IDEA_STAGE);
}

/**
 * The cards for review requests. A batch of ideas is one card while an idea of it waits in the Idea column (plus batches that were open
 * when this visit began, kept in `stay`, so a card does not vanish under the editor's thumb). A batch that names no stories (it was raised
 * when ideas were Proposals) is left out: `papyrus ideas migrate-proposals` turns those Proposals into ideas, which appear in the column.
 */
export function buildNotificationItems(input: {
  requests: ReviewRequest[];
  /** Stage of each idea by lineage id, once read. */
  ideaStages?: Readonly<Record<string, string>>;
  /** Request ids kept on screen in this visit. */
  stay: ReadonlySet<string>;
}): NotificationItems {
  const stages = input.ideaStages ?? {};
  const sections = sectionReviews(input.requests);
  const closedHere = input.requests.filter((request) => request.state !== "open" && input.stay.has(request.id));
  const asItem = (request: ReviewRequest): RequestItem => ({ kind: "request", key: request.id, request });
  const standing = (request: ReviewRequest) => request.state === "open" || input.stay.has(request.id);
  const unique = (items: RequestItem[]) => [...new Map(items.map((item) => [item.key, item])).values()];
  const ideas = sections.ideaBatches.filter((request) => ideaIdsOf(request).length > 0 && (batchHasIdeasWaiting(request, stages) || input.stay.has(request.id))).map(asItem);
  const reviews = [...sections.hardGates, ...sections.softReviews, ...closedHere.filter((request) => request.mode !== "flag" && !isIdeaBatch(request))].filter(standing).map(asItem);
  const flags = [...sections.flags, ...closedHere.filter((request) => request.mode === "flag")].filter(standing).map(asItem);
  return { ideas: unique(ideas), reviews: unique(reviews), flags: unique(flags) };
}

export function sourceHost(address: string): string | null {
  try {
    return new URL(address).hostname.replace(/^www\./i, "") || null;
  } catch {
    return null;
  }
}

// --- what you decided ------------------------------------------------------------------------------------------

export type RecentDecision = {
  key: string;
  kind: "idea" | "reference" | "request";
  word: "Accepted" | "Rejected" | "Acknowledged" | "Answered";
  choice: "accept" | "reject" | "acknowledge" | "answer";
  title: string;
  at: string;
  href: string | null;
  /** The editor's why, when there is one. */
  note: string | null;
};

function requestDecision(request: ReviewRequest): Pick<RecentDecision, "word" | "choice"> | null {
  const answer = request.answer;
  if (request.state !== "answered" || !answer) return null;
  if (answer.decision === "acknowledge" || (answer.decision === "approve" && request.mode === "flag")) return { word: "Acknowledged", choice: "acknowledge" };
  if (answer.decision === "approve") return { word: "Accepted", choice: "accept" };
  if (answer.decision === "reject") return { word: "Rejected", choice: "reject" };
  return { word: "Answered", choice: "answer" };
}

/** What the editor decided most recently, newest first: ideas decided in a batch before ideas moved to the board, other requests and References. "Last few", so a small default. */
export function recentDecisions(requests: ReviewRequest[], references: ReferenceRecord[], demo = false, limit = 5): RecentDecision[] {
  const found = new Map<string, RecentDecision>();
  for (const request of requests) {
    for (const link of request.links) {
      if (!link.decision || !link.id) continue;
      found.set(`${request.id}#${link.id}`, {
        key: `${request.id}#${link.id}`, kind: "idea", word: link.decision.choice === "accept" ? "Accepted" : "Rejected", choice: link.decision.choice,
        title: link.decision.title ?? link.label ?? link.id, at: link.decision.at, href: link.type === "story" ? getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(link.id)}`, demo) : null, note: link.decision.why ?? null,
      });
    }
    for (const entry of request.answer?.drafts ?? []) {
      found.set(`${request.id}#${entry.id}`, {
        key: `${request.id}#${entry.id}`, kind: "idea", word: entry.choice === "accept" ? "Accepted" : "Rejected", choice: entry.choice,
        title: entry.title ?? entry.id, at: entry.at, href: null, note: entry.why ?? null,
      });
    }
    const whole = requestDecision(request);
    if (whole && !request.answer?.drafts?.length) {
      found.set(request.id, { key: request.id, kind: "request", ...whole, title: request.reason, at: request.answer!.at, href: null, note: request.answer!.feedback });
    }
  }
  for (const reference of references) {
    const status = normalizeReferenceCurationStatus(reference.curationStatus);
    if ((status !== "accepted" && status !== "rejected") || !reference.curationStatusUpdatedAt) continue;
    const lineageId = referenceLineageId(reference);
    found.set(`reference#${lineageId}`, {
      key: `reference#${lineageId}`, kind: "reference", word: status === "accepted" ? "Accepted" : "Rejected", choice: status === "accepted" ? "accept" : "reject",
      title: referenceDisplayTitle(reference), at: reference.curationStatusUpdatedAt, href: getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo), note: null,
    });
  }
  return [...found.values()].filter((entry) => entry.at).sort((a, b) => b.at.localeCompare(a.at)).slice(0, limit);
}
