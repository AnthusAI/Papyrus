import type { ReferenceRecord } from "./category-repository";
import { AUTO_ACCEPT_ACTOR, AUTO_ACCEPT_RULE_ACTOR, isAutoAccepted } from "./reference-policy";

/**
 * The "Accepted automatically" list: every current Reference that stands accepted by the Cyclotron (`auto:cyclotron`) or by a monitor's
 * fixed rule (`auto:rule`), newest acceptance first, so an editor can review them and Reject any they disagree with.
 *
 * No new index. A page is read from the accepted partition of `listReferencesByCurationStatusAndUpdatedAt` (newest `curationStatusUpdatedAt`
 * first) and the actor filter is applied by the database, so only matching rows cross the wire. The reader walks forward only as far as it
 * needs to fill one page; it never reads the whole table. See docs/monitoring-cloud.md#reviewing-what-was-accepted-automatically.
 */

/** The URL value of `?status=` that opens this list. */
export const AUTO_ACCEPTED_STATUS_URL = "auto-accepted";

/** How many matches one page of the list holds. */
export const AUTO_ACCEPTED_PAGE_SIZE = 24;

/** The actors whose acceptance is automatic, in the order the filter names them. */
export const AUTO_ACCEPT_ACTORS = [AUTO_ACCEPT_ACTOR, AUTO_ACCEPT_RULE_ACTOR] as const;

/** The server-side filter that keeps only current, automatically accepted References. `corpusId` narrows it to one corpus. */
export function autoAcceptedServerFilter(corpusId?: string): Record<string, unknown> {
  const filter: Record<string, unknown> = {
    versionState: { eq: "current" },
    newsroomFeedKey: { eq: "references" },
    or: AUTO_ACCEPT_ACTORS.map((actor) => ({ curationStatusUpdatedBy: { eq: actor } })),
  };
  if (corpusId) filter.corpusId = { eq: corpusId };
  return filter;
}

export type AutoAcceptedSourcePage = { items: ReferenceRecord[]; nextToken?: string | null };
export type AutoAcceptedPage = { items: ReferenceRecord[]; nextToken: string | null; hasMore: boolean };

/**
 * One page of the list. `readPage` is one filtered read of the accepted partition (a database page can hold fewer matches than were asked
 * for, even none, and still have more behind it), so this keeps reading until `limit` matches are in hand or the partition runs out.
 * Rows are checked again here, so a stale or unfiltered read can never put a human's acceptance into the list.
 */
export async function collectAutoAcceptedPage(
  readPage: (nextToken: string | null) => Promise<AutoAcceptedSourcePage>,
  { nextToken = null, limit = AUTO_ACCEPTED_PAGE_SIZE }: { nextToken?: string | null; limit?: number } = {},
): Promise<AutoAcceptedPage> {
  const items: ReferenceRecord[] = [];
  const seen = new Set<string>();
  let token = nextToken;
  do {
    const page = await readPage(token);
    token = page.nextToken ?? null;
    for (const reference of page.items) {
      if (!reference || seen.has(reference.id) || (reference.versionState ?? "current") !== "current" || !isAutoAccepted(reference)) continue;
      seen.add(reference.id);
      items.push(reference);
    }
  } while (items.length < limit && token);
  return { items, nextToken: token, hasMore: Boolean(token) };
}

/** Newest acceptance first. The server already returns this order; the sort keeps merged pages in it. */
export function compareAutoAcceptedNewestFirst(left: ReferenceRecord, right: ReferenceRecord): number {
  const leftAt = Date.parse(String(left.curationStatusUpdatedAt ?? "")) || 0;
  const rightAt = Date.parse(String(right.curationStatusUpdatedAt ?? "")) || 0;
  if (leftAt !== rightAt) return rightAt - leftAt;
  return String(right.id).localeCompare(String(left.id));
}

/** Every automatically accepted Reference in a list already in memory (the preview and tests; the live page asks the database). */
export function autoAcceptedFromRecords(references: readonly ReferenceRecord[]): ReferenceRecord[] {
  return references.filter((reference) => (reference.versionState ?? "current") === "current" && isAutoAccepted(reference)).sort(compareAutoAcceptedNewestFirst);
}

/** What an editor reads when nothing is waiting for them. */
export const AUTO_ACCEPTED_EMPTY_TEXT =
  "Nothing has been accepted automatically yet, or you have already reviewed everything that was. "
  + "When the Cyclotron or a monitor's rule accepts a reference on its own, it appears here for you to check.";

/** Who accepted it: the monitor's fixed rule, or the Cyclotron's confidence. The reason text says more; this is the plain label. */
export function autoAcceptedBy(reference: { curationStatusUpdatedBy?: unknown }): "rule" | "cyclotron" {
  return String(reference.curationStatusUpdatedBy ?? "").trim() === AUTO_ACCEPT_RULE_ACTOR ? "rule" : "cyclotron";
}

/**
 * How sure the Cyclotron was, as a share from 0 to 1, read from the reason it wrote ("it was 95.0% sure this is relevant", written by
 * src/papyrus_content/auto_accept.py). Null for a rule acceptance, which has no confidence, and for any reason in other words. The list
 * prefers the Cyclotron's own current verdict when the page has it; this is for when it has not been read.
 */
export function confidenceFromReason(reason: unknown): number | null {
  const match = /\b(\d{1,3}(?:\.\d+)?)% sure\b/.exec(String(reason ?? ""));
  if (!match) return null;
  const share = Number(match[1]) / 100;
  return share >= 0 && share <= 1 ? share : null;
}

/**
 * The copy of a Reference to show when the list holds one read from the database and the page holds another (it was loaded earlier, or
 * an editor has voted since): whichever records the later vote. An editor's Reject or Accept in this session is newer than the read, so
 * the card follows it.
 */
export function laterVoteRecord(read: ReferenceRecord, held: ReferenceRecord | undefined): ReferenceRecord {
  if (!held) return read;
  const readAt = Date.parse(String(read.curationStatusUpdatedAt ?? "")) || 0;
  const heldAt = Date.parse(String(held.curationStatusUpdatedAt ?? "")) || 0;
  return heldAt > readAt ? held : read;
}
