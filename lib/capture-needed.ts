/**
 * Accepted References whose content we could not collect, for the newsroom home page ("Needs capture"): a title and an address, say, behind an
 * I-am-not-a-robot gate. Worth a person's effort, best first, by uploading a PDF or pasting the text (docs/notification-center.md).
 *
 * Which ones: accepted (never rejected, archived or superseded), `captureState` not `full`, and not `running` (a capture in flight will finish
 * by itself). Order: most stars first, then newest; an unstarred one after every starred one.
 *
 * How they are read, never by scanning the References: the star partitions 5 down to 1 (`<corpusId>#stars#<n>`, merged by stars then arrival), filtered
 * to what is wanted as each page is read, then the `#rated` feed-state partition newest first for the unstarred ones, stopping the moment enough
 * are found. A site whose schema lacks the star index still gets its unstarred ones; a site that fails both gets none, and the rest of the page
 * is untouched.
 */
import type { ReferenceRecord } from "./category-repository";
import {
  FEED_READ_PAGE_SIZE,
  MergedFeedReader,
  feedReaderFromRecords,
  feedStateKeys,
  starReaderFromRecords,
  liveStarRows,
  starFeedKeys,
  type FeedStreamReader,
} from "./reference-feed-pages";
import { starsOf } from "./reference-policy";

/** How many the home page lists before "See all". */
export const CAPTURE_NEEDED_SHOWN = 3;

/** Whether a Reference's stored capture state asks for a person: not captured in full, and not being captured right now. */
export function needsPersonToCapture(reference: Pick<ReferenceRecord, "captureState">): boolean {
  return reference.captureState !== "full" && reference.captureState !== "running";
}

/** A reader that keeps only the rows that ask for a person (the accepted filter is `liveStarRows`' or the caller's). */
export function uncapturedRows(read: FeedStreamReader): FeedStreamReader {
  return async (query) => {
    const page = await read(query);
    return { ...page, items: page.items.filter(needsPersonToCapture) };
  };
}

/** Accepted rows of a `#rated` page: the partition holds the rejected too. */
function acceptedOnly(read: FeedStreamReader): FeedStreamReader {
  return liveStarRows(read, "accepted");
}

export type CaptureNeededSource = {
  corpusIds: readonly string[];
  readStarStream: FeedStreamReader;
  readStream: FeedStreamReader;
};

async function fill(reader: MergedFeedReader, found: ReferenceRecord[], count: number, skip: (reference: ReferenceRecord) => boolean) {
  while (found.length < count && reader.hasMore) {
    for (const reference of await reader.more(count - found.length)) if (!skip(reference)) found.push(reference);
  }
}

/** The first `count` References that need a person to capture them, in the order above. Never throws: a failed read yields what was found. */
export async function readCaptureNeeded(source: CaptureNeededSource, count = CAPTURE_NEEDED_SHOWN): Promise<ReferenceRecord[]> {
  const found: ReferenceRecord[] = [];
  const pageSize = Math.max(count, FEED_READ_PAGE_SIZE);
  try {
    const starred = new MergedFeedReader({ keys: starFeedKeys(source.corpusIds, 1), sort: "quality", read: uncapturedRows(acceptedOnly(source.readStarStream)), pageSize });
    await fill(starred, found, count, () => false);
  } catch {
    // No star index on this site (or it could not be read): the unstarred ones below still list.
  }
  if (found.length >= count) return found.slice(0, count);
  try {
    const rated = new MergedFeedReader({ keys: feedStateKeys(source.corpusIds, "rated"), sort: "newest", read: uncapturedRows(acceptedOnly(source.readStream)), pageSize });
    await fill(rated, found, count, (reference) => starsOf(reference) > 0);
  } catch {
    // Keep what the stars gave.
  }
  return found.slice(0, count);
}

/** The same reads served from records held in memory (the demo, the local preview and the test editor mock). */
export function captureNeededSourceFromRecords(records: readonly ReferenceRecord[]): CaptureNeededSource {
  return {
    corpusIds: [...new Set(records.map((record) => record.corpusId))],
    readStarStream: starReaderFromRecords(records),
    readStream: feedReaderFromRecords(records),
  };
}
