/**
 * The Notification Center as a feed of cards ("What needs me?"): which cards there are, how they are counted, filtered and
 * worded. Pure functions, so the page and its tests share them. A review request that covers several AI drafts is not shown as a
 * batch: each draft is its own card, with a small caption saying which run it came from. The request still closes itself when
 * its last draft is decided (components/notification-center.tsx).
 */
import type { ReferenceRecord } from "./category-repository";
import { referenceDisplayTitle, referenceLineageId } from "./newsroom-references";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import type { ReferencePreview } from "./reference-preview";
import { draftDecisionOf, type DraftView } from "./review-drafts";
import { draftIdsOf, isDraftReview, proposalHref, sectionReviews, type DraftDecision, type ReviewRequest } from "./review-requests";
import { getNewsroomNavHref } from "./newsroom-nav";

export type NotificationFilter = "all" | "drafts" | "references" | "other";
export const NOTIFICATION_FILTERS: readonly NotificationFilter[] = ["all", "drafts", "references", "other"];
export const FILTER_LABELS: Record<NotificationFilter, string> = { all: "All", drafts: "Drafts", references: "References", other: "Other" };

export type DraftItem = {
  kind: "draft";
  /** `<request id>#<draft id>`. */
  key: string;
  request: ReviewRequest;
  draftId: string;
  /** Undefined while the Proposal is still loading. */
  view: DraftView | undefined;
  decision: DraftDecision | null;
};

/** A request that is decided as a whole: a hard gate, a soft review of something that is not a draft, or a flag. */
export type RequestItem = { kind: "request"; key: string; request: ReviewRequest };

export type NotificationItems = {
  drafts: DraftItem[];
  /** Hard gates first, then the other soft reviews, soonest deadline first. */
  reviews: RequestItem[];
  /** For your information: flags. */
  flags: RequestItem[];
  counts: NotificationCounts;
};

export type NotificationCounts = { drafts: number; references: number; other: number };

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

const NO_FALLBACK = { by: "", at: "" } as const;

/**
 * The cards for review requests. A draft review becomes one card per draft: undecided drafts of open requests, plus drafts decided in
 * this visit (`stay`, keyed `<request id>#<draft id>`) so a card does not vanish under the editor's thumb. Drafts that are not Proposals
 * on this site cannot be opened here; when none can, the request itself is one card that takes Accept or Reject.
 */
export function buildNotificationItems(input: {
  requests: ReviewRequest[];
  drafts: Readonly<Record<string, DraftView | undefined>>;
  missingDrafts: ReadonlySet<string>;
  draftsState: "loading" | "ready" | "failed";
  /** Draft keys and request ids decided in this visit. */
  stay: ReadonlySet<string>;
  referenceCount: number;
}): NotificationItems {
  const sections = sectionReviews(input.requests);
  const closedHere = input.requests.filter((request) => request.state !== "open" && input.stay.has(request.id));
  const draftItems: DraftItem[] = [];
  const requestLevel: ReviewRequest[] = [];
  const draftRequests = [...sections.draftBatches, ...input.requests.filter((request) => request.state !== "open" && isDraftReview(request) && draftIdsOf(request).some((id) => input.stay.has(`${request.id}#${id}`)))];
  for (const request of draftRequests) {
    const available = draftIdsOf(request).filter((id) => !input.missingDrafts.has(id));
    if (request.state === "open" && input.draftsState === "ready" && available.length === 0) {
      requestLevel.push(request);
      continue;
    }
    for (const draftId of available) {
      const key = `${request.id}#${draftId}`;
      const view = input.drafts[draftId];
      const decision = draftDecisionOf(request.links.find((link) => link.id === draftId), view, NO_FALLBACK);
      const waiting = request.state === "open" && !decision;
      if (waiting || input.stay.has(key)) draftItems.push({ kind: "draft", key, request, draftId, view, decision });
    }
  }
  const asItem = (request: ReviewRequest): RequestItem => ({ kind: "request", key: request.id, request });
  const standing = (request: ReviewRequest) => request.state === "open" || input.stay.has(request.id);
  const reviews = [
    ...sections.hardGates,
    ...sections.softReviews,
    ...requestLevel,
    ...closedHere.filter((request) => request.mode !== "flag" && !isDraftReview(request)),
  ].filter(standing).map(asItem);
  const flags = [...sections.flags, ...closedHere.filter((request) => request.mode === "flag")].filter(standing).map(asItem);
  return {
    drafts: draftItems,
    reviews: [...new Map(reviews.map((item) => [item.key, item])).values()],
    flags: [...new Map(flags.map((item) => [item.key, item])).values()],
    counts: {
      drafts: draftItems.filter((item) => !item.decision).length,
      references: input.referenceCount,
      other: [...reviews, ...flags].filter((item) => item.request.state === "open").length,
    },
  };
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "3 drafts and 12 references waiting for you"; "All caught up" when nothing waits. */
export function waitingText(counts: NotificationCounts): string {
  const parts = [
    counts.drafts ? plural(counts.drafts, "draft") : null,
    counts.references ? plural(counts.references, "reference") : null,
    counts.other ? plural(counts.other, "other item") : null,
  ].filter((part): part is string => part !== null);
  if (!parts.length) return "All caught up";
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `${list} waiting for you`;
}

export function filterCount(filter: NotificationFilter, counts: NotificationCounts): number {
  return filter === "all" ? counts.drafts + counts.references + counts.other : counts[filter];
}

/** Which sections a filter shows. */
export function showsSection(filter: NotificationFilter, section: "drafts" | "references" | "other"): boolean {
  return filter === "all" || filter === section;
}

// --- sources, pictures ----------------------------------------------------------------------------------------

function normalizedAddress(address: string): string {
  try {
    const url = new URL(address);
    return `${url.hostname.replace(/^www\./i, "").toLowerCase()}${url.pathname.replace(/\/+$/, "")}${url.search}`;
  } catch {
    return address.trim().toLowerCase();
  }
}

/** The previews of References by the address they were saved from, so a draft's cited source finds its picture. */
export function previewsBySourceAddress(references: ReferenceRecord[], previews: ReadonlyMap<string, ReferencePreview>): Map<string, ReferencePreview> {
  const found = new Map<string, ReferencePreview>();
  for (const reference of references) {
    const preview = previews.get(referenceLineageId(reference));
    if (preview && reference.sourceUri) found.set(normalizedAddress(reference.sourceUri), preview);
  }
  return found;
}

/** The first cited source that has a picture, with the site name its preview gives. */
export function draftPicture(view: DraftView | undefined, bySource: ReadonlyMap<string, ReferencePreview>): { imageUrl: string | null; siteName: string | null; host: string | null } {
  const sources = view?.sources ?? [];
  const host = sources.find((source) => source.url)?.url ? sourceHost(sources.find((source) => source.url)!.url!) : null;
  for (const source of sources) {
    const preview = source.url ? bySource.get(normalizedAddress(source.url)) : undefined;
    if (preview?.imageUrl) return { imageUrl: preview.imageUrl, siteName: preview.siteName, host: source.url ? sourceHost(source.url) : host };
  }
  return { imageUrl: null, siteName: null, host };
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
  kind: "draft" | "reference" | "request";
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

/** What the editor decided most recently, newest first: drafts, other requests and References. "Last few", so a small default. */
export function recentDecisions(requests: ReviewRequest[], references: ReferenceRecord[], demo = false, limit = 5): RecentDecision[] {
  const found = new Map<string, RecentDecision>();
  for (const request of requests) {
    for (const link of request.links) {
      if (!link.decision || !link.id) continue;
      found.set(`${request.id}#${link.id}`, {
        key: `${request.id}#${link.id}`, kind: "draft", word: link.decision.choice === "accept" ? "Accepted" : "Rejected", choice: link.decision.choice,
        title: link.decision.title ?? link.label ?? link.id, at: link.decision.at, href: proposalHref(link.id, demo), note: link.decision.why ?? null,
      });
    }
    for (const entry of request.answer?.drafts ?? []) {
      found.set(`${request.id}#${entry.id}`, {
        key: `${request.id}#${entry.id}`, kind: "draft", word: entry.choice === "accept" ? "Accepted" : "Rejected", choice: entry.choice,
        title: entry.title ?? entry.id, at: entry.at, href: proposalHref(entry.id, demo), note: entry.why ?? null,
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
