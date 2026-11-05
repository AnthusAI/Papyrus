/**
 * The References page search box (docs/reference-search.md): the shapes the `searchReferences` query answers with, the words a card shows for
 * how it matched, and a small in-browser matcher used only where there is no backend (local preview and the tests' fixture).
 */
import type { ReferenceRecord } from "./category-repository";
import { referenceFeedKeys } from "./reference-feed-keys";
import { matchesCaptured, normalizeReferenceCurationStatus, starsOf, type CapturedChoice } from "./reference-policy";

export type ReferenceSearchShow = "unrated" | "rated" | "all" | "accepted";
/** What the query itself accepts: the References page asks for the four above; the Search page also asks for `rejected` alone. */
export type ReferenceSearchQueryShow = ReferenceSearchShow | "rejected";
export type ReferenceSearchLane = { status: "ok" | "failed"; message?: string };
export type ReferenceSearchMatch = { reference: ReferenceRecord; matchedBy: Array<"keyword" | "meaning">; matchedFields: string[] };
export type ReferenceSearchPage = {
  items: ReferenceSearchMatch[];
  nextCursor: string | null;
  lanes: { keyword: ReferenceSearchLane; meaning: ReferenceSearchLane };
};
/** Relevance keeps the site's fused order; Newest is by arrival; Quality is stars first (an unstarred match last, so a search never loses one), then newest. */
export type ReferenceSearchSort = "relevance" | "newest" | "quality";
/** The fewest stars a match must have (3, 4 or 5); null or absent is Any. */
export type ReferenceSearchMinStars = 3 | 4 | 5 | null;
export type ReferenceSearchInput = {
  query: string;
  show: ReferenceSearchQueryShow;
  limit: number;
  cursor: string | null;
  sort?: ReferenceSearchSort;
  minStars?: ReferenceSearchMinStars;
  /** Captured: `yes` keeps matches whose content we hold in full, `no` the rest. Absent is Any. */
  captured?: CapturedChoice;
};
export type ReferenceSearchReader = (input: ReferenceSearchInput) => Promise<ReferenceSearchPage>;

export const SEARCH_PAGE_SIZE = 24;
const FIELD_LABELS: Record<string, string> = { title: "title", authors: "author", sourceUri: "link", externalItemId: "id" };

/** What the box submits: spaces collapsed, nothing when it is blank. */
export function normalizeSearchQuery(raw: string | null | undefined): string {
  return (raw ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, 500);
}

/** `?q=` from a location's search string. */
export function searchQueryFromLocation(search: string): string {
  return normalizeSearchQuery(new URLSearchParams(search).get("q"));
}

/** A page path with the search in its query (`?q=`), or the bare path when not searching. */
export function pathWithSearch(path: string, query: string): string {
  const [base] = path.split("?");
  return query ? `${base}?q=${encodeURIComponent(query)}` : base!;
}

/** "title, author", "meaning" or "title and meaning": what a card says matched, never colour alone. */
export function matchedLabel(matchedBy: readonly string[], matchedFields: readonly string[]): string {
  const fields = matchedFields.map((field) => FIELD_LABELS[field] ?? field);
  const words = fields.join(", ");
  if (!matchedBy.includes("meaning")) return words;
  return words ? `${words} and meaning` : "meaning";
}

/** The sentence under the controls when one lane could not run, or null when both did (or neither: that is an error, not a notice). */
export function laneNotice(lanes: ReferenceSearchPage["lanes"]): string | null {
  const wordsDown = lanes.keyword.status === "failed";
  const meaningDown = lanes.meaning.status === "failed";
  if (meaningDown && !wordsDown) return "Searched by words only: meaning search is unavailable";
  if (wordsDown && !meaningDown) return "Searched by meaning only: word search is unavailable";
  return null;
}

export function bothLanesFailed(lanes: ReferenceSearchPage["lanes"]): boolean {
  return lanes.keyword.status === "failed" && lanes.meaning.status === "failed";
}

/** Defensive read of the query's AWSJSON answer. */
export function parseSearchPage(value: unknown): ReferenceSearchPage {
  let parsed = value;
  if (typeof parsed === "string") {
    try { parsed = JSON.parse(parsed); } catch { throw new Error("The search answered with something unreadable."); }
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("The search answered with nothing.");
  const page = parsed as Partial<ReferenceSearchPage>;
  if (!Array.isArray(page.items)) throw new Error("The search answered without results.");
  const lane = (value: ReferenceSearchLane | undefined): ReferenceSearchLane => (value && value.status === "failed" ? { status: "failed", message: value.message } : { status: "ok" });
  return {
    items: page.items.filter((item): item is ReferenceSearchMatch => Boolean(item?.reference)).map((item) => ({
      reference: item.reference,
      matchedBy: Array.isArray(item.matchedBy) ? item.matchedBy : [],
      matchedFields: Array.isArray(item.matchedFields) ? item.matchedFields : [],
    })),
    nextCursor: typeof page.nextCursor === "string" && page.nextCursor ? page.nextCursor : null,
    lanes: { keyword: lane(page.lanes?.keyword), meaning: lane(page.lanes?.meaning) },
  };
}

/** Local preview only: a word stands for a few titles it shares no letters with, so the preview can show "Matched: meaning" without a vector index. */
export const PREVIEW_SEARCH_MEANING: Readonly<Record<string, readonly string[]>> = { memory: ["recall", "remember", "notebook"] };

// --- the results page: kinds, statuses and groups ----------------------------------------------------------------------------------------------

/** The status buttons on the results page. `any` is every Reference the editor may see; the others narrow to one status. */
export type SearchStatusChoice = "any" | "pending" | "accepted" | "rejected";
export const SEARCH_STATUS_CHOICES: readonly SearchStatusChoice[] = ["any", "pending", "accepted", "rejected"];
const SHOW_FOR_STATUS: Record<SearchStatusChoice, ReferenceSearchQueryShow> = { any: "all", pending: "unrated", accepted: "accepted", rejected: "rejected" };

export function showForStatus(status: SearchStatusChoice): ReferenceSearchQueryShow {
  return SHOW_FOR_STATUS[status];
}

/** `?status=` from a location's search string; anything else is Any. */
export function statusFromLocation(search: string): SearchStatusChoice {
  const value = new URLSearchParams(search).get("status");
  return (SEARCH_STATUS_CHOICES as readonly string[]).includes(value ?? "") ? (value as SearchStatusChoice) : "any";
}

/**
 * Which kind of result this is, in words:
 *  - `title`: the typed words were found in the Reference's title (an exact word hit);
 *  - `word`: found in its authors, link or id, not its title;
 *  - `related`: no typed word was found; it is close in meaning only.
 */
export type SearchResultKind = "title" | "word" | "related";

export function searchResultKind(match: Pick<ReferenceSearchMatch, "matchedBy" | "matchedFields">): SearchResultKind {
  if (!match.matchedBy.includes("keyword")) return "related";
  return match.matchedFields.includes("title") ? "title" : "word";
}

export const SEARCH_KIND_LABEL: Record<SearchResultKind, string> = { title: "Title match", word: "Word match", related: "Related" };

/** The sentence under a result saying why it is there. */
export function searchKindExplanation(match: Pick<ReferenceSearchMatch, "matchedBy" | "matchedFields">): string {
  const kind = searchResultKind(match);
  if (kind === "related") return "Close in meaning to your search; the words are not in it.";
  const where = match.matchedFields.map((field) => FIELD_LABELS[field] ?? field).join(" and ");
  return `Your words are in the ${where}${match.matchedBy.includes("meaning") ? ", and it is close in meaning too" : ""}.`;
}

/** The status in words (a Reference with no answer yet is Pending). */
export function searchStatusWord(reference: Pick<ReferenceRecord, "curationStatus">): "Pending" | "Accepted" | "Rejected" {
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  return status === "accepted" ? "Accepted" : status === "rejected" ? "Rejected" : "Pending";
}

/** Word hits first, then the related ones, each keeping the server's order. The server already ranks word hits above related ones; this only splits them. */
export function splitSearchResults(items: readonly ReferenceSearchMatch[]): { wordHits: ReferenceSearchMatch[]; related: ReferenceSearchMatch[] } {
  return {
    wordHits: items.filter((item) => searchResultKind(item) !== "related"),
    related: items.filter((item) => searchResultKind(item) === "related"),
  };
}

// --- the matcher for local preview and fixtures ------------------------------------------------------------------------------------------------

const fold = (text: string) => text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const words = (text: string) => fold(text).match(/[\p{L}\p{N}]+/gu) ?? [];

/**
 * Not the real search: every word of the query must start a word in the title, authors, link or id (the same fields the site searches), and the
 * optional `meaning` map says which other words stand for a query word (a stand-in for the vector index). Pages with an opaque numeric cursor.
 */
export function previewSearch(
  records: readonly ReferenceRecord[],
  input: ReferenceSearchInput,
  options: { meaning?: Readonly<Record<string, readonly string[]>>; lanes?: ReferenceSearchPage["lanes"] } = {},
): ReferenceSearchPage {
  const terms = [...new Set(words(input.query))];
  const matches: ReferenceSearchMatch[] = [];
  for (const record of records) {
    const keys = referenceFeedKeys(record);
    const state = record.feedStateKey ?? keys.feedStateKey;
    if (!state) continue;
    if (input.show === "unrated" && !state.endsWith("#unrated")) continue;
    if (input.show === "rated" && !state.endsWith("#rated")) continue;
    if (input.show === "accepted" && !(state.endsWith("#rated") && normalizeReferenceCurationStatus(record.curationStatus) === "accepted")) continue;
    if (input.show === "rejected" && !(state.endsWith("#rated") && normalizeReferenceCurationStatus(record.curationStatus) === "rejected")) continue;
    const fields: Record<string, string[]> = {
      title: words(record.title ?? ""), authors: words((record.authors ?? []).join(" ")), sourceUri: words(record.sourceUri ?? ""), externalItemId: words(record.externalItemId ?? ""),
    };
    const hit = (term: string) => Object.entries(fields).filter(([, tokens]) => tokens.some((token) => token === term || (term.length >= 3 && token.startsWith(term)))).map(([name]) => name);
    const perTerm = terms.map(hit);
    const byWords = terms.length > 0 && perTerm.every((found) => found.length > 0);
    const matchedFields = [...new Set(perTerm.flat())];
    const byMeaning = terms.some((term) => (options.meaning?.[term] ?? []).some((related) => fields.title.some((token) => token.startsWith(related))));
    if (!byWords && !byMeaning) continue;
    matches.push({ reference: { ...record, ...keys, feedStateKey: state }, matchedBy: [...(byWords ? ["keyword" as const] : []), ...(byMeaning ? ["meaning" as const] : [])], matchedFields: byWords ? matchedFields : [] });
  }
  const rank = (match: ReferenceSearchMatch) => (match.matchedBy.length === 2 ? 0 : match.matchedBy[0] === "keyword" ? 1 : 2);
  matches.sort((left, right) => rank(left) - rank(right) || (right.reference.feedArrivalAt ?? "").localeCompare(left.reference.feedArrivalAt ?? "") || left.reference.id.localeCompare(right.reference.id));
  const arrival = (match: ReferenceSearchMatch) => match.reference.feedArrivalAt ?? "";
  const starred = input.minStars ? matches.filter((match) => starsOf(match.reference) >= input.minStars!) : matches;
  const kept = input.captured && input.captured !== "any" ? starred.filter((match) => matchesCaptured(match.reference, input.captured!)) : starred;
  // Stable sorts, as the site's: a tie keeps the relevance order.
  if (input.sort === "newest") kept.sort((left, right) => arrival(right).localeCompare(arrival(left)));
  else if (input.sort === "quality") kept.sort((left, right) => starsOf(right.reference) - starsOf(left.reference) || arrival(right).localeCompare(arrival(left)));
  matches.splice(0, matches.length, ...kept);
  const start = input.cursor ? Number(input.cursor) || 0 : 0;
  const page = matches.slice(start, start + input.limit);
  const next = start + page.length;
  return { items: page, nextCursor: next < matches.length ? String(next) : null, lanes: options.lanes ?? { keyword: { status: "ok" }, meaning: { status: "ok" } } };
}
