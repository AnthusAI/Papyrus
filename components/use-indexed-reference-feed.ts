"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import {
  SEARCH_PAGE_SIZE,
  normalizeSearchQuery,
  pathWithSearch,
  searchQueryFromLocation,
  bothLanesFailed,
  laneNotice,
  matchedLabel,
  type ReferenceSearchMinStars,
  type ReferenceSearchPage,
  type ReferenceSearchReader,
  type ReferenceSearchShow,
  type ReferenceSearchSort,
} from "../lib/reference-search";
import type { FeedCaptured, FeedMinStars } from "../lib/reference-feed-ranking";
import { mediumFeedKeys, mediumRows, type FeedMedium } from "../lib/reference-medium-feed";
import {
  FEED_READ_PAGE_SIZE,
  MergedFeedReader,
  acceptedRows,
  capturedRows,
  feedStateKeys,
  liveStarRows,
  starFeedKeys,
  type FeedStreamReader,
  type FeedStreamShow,
  type FeedStreamSort,
} from "../lib/reference-feed-pages";

export type IndexedFeedSource = {
  /** The corpora whose partitions are read (a site can have several). */
  loadCorpusIds: () => Promise<string[]>;
  /** One page of one partition from the feed-state index. */
  readStream: FeedStreamReader;
  /** One page of one star partition (`<corpusId>#stars#<n>`), newest arrival first. Without it the Quality sort and a minimum of stars cannot be read. */
  readStarStream?: FeedStreamReader;
  /** One page of one medium partition (`<corpusId>#<medium>#<pending|accepted|rejected>`), newest arrival first. Without it a medium cannot be chosen. */
  readMediumStream?: FeedStreamReader;
  /** The search box's query. Without it the page has no search box. */
  search?: ReferenceSearchReader;
};

type Status = "idle" | "loading" | "ready" | "error";

/**
 * The References feed, a page at a time from the feed-state indexes, in the order the index gives (merged across corpora).
 * The Quality sort and a minimum of stars read the star partitions instead (one per star level, merged by `MergedFeedReader`), keeping the rows
 * the chosen Show lets through.
 * The first page is one round of reads; `loadMore` reads one more round when the reader nears the end. Nothing else is read.
 * A failed first read leaves `status` at "error" with a sentence and `retry` reads it again; a failed later page keeps the cards already
 * shown and sets `moreError`.
 */
export function useIndexedReferenceFeed({
  enabled,
  source,
  sort,
  show,
  minStars = 0,
  captured = "any",
  medium = "any",
  pageSize = FEED_READ_PAGE_SIZE,
}: {
  enabled: boolean;
  source: IndexedFeedSource | undefined;
  sort: FeedStreamSort;
  show: FeedStreamShow;
  /** The fewest stars to show; 0 is Any. */
  minStars?: FeedMinStars;
  /** Captured: pages are filtered as they are read (`capturedRows`); Any reads them as they are. */
  captured?: FeedCaptured;
  /** Medium: a medium reads the medium partitions (newest first); with stars it keeps that medium's rows of the star partitions. Any reads as before. */
  medium?: FeedMedium;
  pageSize?: number;
}) {
  const [records, setRecords] = useState<ReferenceRecord[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [readAt, setReadAt] = useState(0);
  const reader = useRef<MergedFeedReader | null>(null);
  const generation = useRef(0);
  const busy = useRef(false);
  const sourceRef = useRef(source);
  sourceRef.current = source;
  const active = enabled && Boolean(source);

  const describe = (failure: unknown, fallback: string) => (failure instanceof Error && failure.message ? failure.message : fallback);

  const start = useCallback(async () => {
    const mine = ++generation.current;
    busy.current = true;
    reader.current = null;
    setRecords([]);
    setStatus("loading");
    setError(null);
    setMoreError(null);
    setHasMore(false);
    setReadAt(Date.now());
    try {
      const current = sourceRef.current!;
      const corpusIds = await current.loadCorpusIds();
      if (mine !== generation.current) return;
      const byStars = sort === "quality" || minStars > 0;
      if (byStars && !current.readStarStream) throw new Error("This site cannot read References by stars.");
      if (medium !== "any" && !byStars && !current.readMediumStream) throw new Error("This site cannot read References by medium.");
      const next = byStars
        ? new MergedFeedReader({ keys: starFeedKeys(corpusIds, minStars), sort, read: capturedRows(mediumRows(liveStarRows(current.readStarStream!, show), medium), captured), pageSize })
        : medium !== "any"
          // The medium index is by arrival: Predictions is never asked for here (the controls move it to Newest).
          ? new MergedFeedReader({ keys: mediumFeedKeys(corpusIds, medium, show), sort: "newest", read: capturedRows(current.readMediumStream!, captured), pageSize })
          : new MergedFeedReader({ keys: feedStateKeys(corpusIds, show), sort, read: capturedRows(acceptedRows(current.readStream, show), captured), pageSize });
      reader.current = next;
      const first = await next.more(pageSize);
      if (mine !== generation.current) return;
      setRecords(first);
      setHasMore(next.hasMore);
      setStatus("ready");
    } catch (failure) {
      if (mine !== generation.current) return;
      setError(describe(failure, "The References could not be read."));
      setStatus("error");
    } finally {
      if (mine === generation.current) busy.current = false;
    }
  }, [captured, medium, minStars, pageSize, show, sort]);

  useEffect(() => {
    if (!active) {
      generation.current += 1;
      busy.current = false;
      setStatus("idle");
      setRecords([]);
      return;
    }
    void start();
    return () => { generation.current += 1; };
  }, [active, start]);

  const loadMore = useCallback(async () => {
    const current = reader.current;
    if (!current || busy.current || !current.hasMore) return;
    const mine = generation.current;
    busy.current = true;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const more = await current.more(pageSize);
      if (mine !== generation.current) return;
      setRecords((existing) => {
        const known = new Set(existing.map((record) => record.id));
        return [...existing, ...more.filter((record) => !known.has(record.id))];
      });
      setHasMore(current.hasMore);
    } catch (failure) {
      if (mine === generation.current) setMoreError(describe(failure, "The next page could not be read."));
    } finally {
      if (mine === generation.current) { busy.current = false; setLoadingMore(false); }
    }
  }, [pageSize]);

  const retry = useCallback(() => {
    if (status === "error") void start();
    else void loadMore();
  }, [loadMore, start, status]);

  return { records, status, error, moreError, hasMore, loadingMore, loadMore, retry, readAt, reads: () => reader.current?.reads ?? 0 };
}

const lineageOf = (record: ReferenceRecord) => record.lineageId ?? record.id;

/**
 * The search results as a feed: the same shape the indexed feed gives (`records`, `status`, `loadMore`, `retry`), in the order the site ranks them
 * (words and meaning fused), plus how each card matched. A search is read a page at a time with the site's opaque cursor; a card already shown is never
 * added again. One lane failing keeps the results and sets `notice`; both failing is an `error`.
 */
export function useReferenceSearchFeed({
  enabled,
  query,
  show,
  sort = "relevance",
  minStars = 0,
  captured = "any",
  read,
  pageSize = SEARCH_PAGE_SIZE,
}: {
  enabled: boolean;
  query: string;
  show: ReferenceSearchShow;
  sort?: ReferenceSearchSort;
  /** The fewest stars a match must have; 0 is Any. */
  minStars?: FeedMinStars;
  /** Captured: the site's search keeps the matches whose content we hold in full (Yes) or the rest (No). */
  captured?: FeedCaptured;
  read: ReferenceSearchReader | undefined;
  pageSize?: number;
}) {
  const [records, setRecords] = useState<ReferenceRecord[]>([]);
  const [matches, setMatches] = useState<ReadonlyMap<string, string>>(() => new Map());
  const [notice, setNotice] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [readAt, setReadAt] = useState(0);
  const cursor = useRef<string | null>(null);
  const generation = useRef(0);
  const busy = useRef(false);
  const readRef = useRef(read);
  readRef.current = read;
  const active = enabled && Boolean(read) && query.trim() !== "";

  const describe = (failure: unknown, fallback: string) => (failure instanceof Error && failure.message ? failure.message : fallback);
  const minimum: ReferenceSearchMinStars = minStars === 0 ? null : minStars;
  const labelsOf = (page: ReferenceSearchPage) => page.items.map((item) => [lineageOf(item.reference), matchedLabel(item.matchedBy, item.matchedFields)] as const);

  const start = useCallback(async () => {
    const mine = ++generation.current;
    busy.current = true;
    cursor.current = null;
    setRecords([]);
    setMatches(new Map());
    setNotice(null);
    setStatus("loading");
    setError(null);
    setMoreError(null);
    setHasMore(false);
    setReadAt(Date.now());
    try {
      const page = await readRef.current!({ query, show, sort, minStars: minimum, captured, limit: pageSize, cursor: null });
      if (mine !== generation.current) return;
      if (bothLanesFailed(page.lanes)) throw new Error("Neither word search nor meaning search could run. Try again in a moment.");
      const seen = new Set<string>();
      const fresh = page.items.filter((item) => !seen.has(lineageOf(item.reference)) && Boolean(seen.add(lineageOf(item.reference))));
      setRecords(fresh.map((item) => item.reference));
      setMatches(new Map(labelsOf({ ...page, items: fresh })));
      setNotice(laneNotice(page.lanes));
      cursor.current = page.nextCursor;
      setHasMore(Boolean(page.nextCursor));
      setStatus("ready");
    } catch (failure) {
      if (mine !== generation.current) return;
      setError(describe(failure, "The search could not be run."));
      setStatus("error");
    } finally {
      if (mine === generation.current) busy.current = false;
    }
  }, [captured, minimum, pageSize, query, show, sort]);

  useEffect(() => {
    if (!active) {
      generation.current += 1;
      busy.current = false;
      setStatus("idle");
      setRecords([]);
      setMatches(new Map());
      setNotice(null);
      setHasMore(false);
      return;
    }
    void start();
    return () => { generation.current += 1; };
  }, [active, start]);

  const loadMore = useCallback(async () => {
    if (!cursor.current || busy.current || !readRef.current) return;
    const mine = generation.current;
    busy.current = true;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await readRef.current({ query, show, sort, minStars: minimum, captured, limit: pageSize, cursor: cursor.current });
      if (mine !== generation.current) return;
      setRecords((existing) => {
        const known = new Set(existing.map(lineageOf));
        const added = page.items.filter((item) => !known.has(lineageOf(item.reference)) && Boolean(known.add(lineageOf(item.reference))));
        return [...existing, ...added.map((item) => item.reference)];
      });
      setMatches((existing) => {
        const next = new Map(existing);
        for (const [id, label] of labelsOf(page)) if (!next.has(id)) next.set(id, label);
        return next;
      });
      const laneMessage = laneNotice(page.lanes);
      if (laneMessage) setNotice(laneMessage);
      cursor.current = page.nextCursor;
      setHasMore(Boolean(page.nextCursor));
    } catch (failure) {
      if (mine === generation.current) setMoreError(describe(failure, "The next page could not be read."));
    } finally {
      if (mine === generation.current) { busy.current = false; setLoadingMore(false); }
    }
  }, [captured, minimum, pageSize, query, show, sort]);

  const retry = useCallback(() => {
    if (status === "error" || notice) void start();
    else void loadMore();
  }, [loadMore, notice, start, status]);

  return { records, matches, notice, status, error, moreError, hasMore, loadingMore, loadMore, retry, readAt, reads: () => 0 };
}

/**
 * The search box's state: the submitted query (also in the URL as `?q=`, followed by the browser's Back and Forward), the Show and Sort choices that
 * belong to the search (it opens on All and on Relevance, and neither is saved), the saved minimum of stars and Captured it shares with the feed, and the results.
 * Clearing the search leaves the saved Sort, Show and minimum as they were.
 */
export function useFeedSearch({ enabled, read, onChange, minStars = 0, captured = "any" }: { enabled: boolean; read: ReferenceSearchReader | undefined; onChange?: () => void; minStars?: FeedMinStars; captured?: FeedCaptured }) {
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<ReferenceSearchShow>("all");
  const [sort, setSort] = useState<ReferenceSearchSort>("relevance");
  const searching = enabled && Boolean(read) && query !== "";
  const feed = useReferenceSearchFeed({ enabled: searching, query, show, sort, minStars, captured, read });
  useEffect(() => {
    const fromUrl = () => setQuery(searchQueryFromLocation(window.location.search));
    fromUrl();
    window.addEventListener("popstate", fromUrl);
    return () => window.removeEventListener("popstate", fromUrl);
  }, []);
  const submit = useCallback((raw: string) => {
    const next = normalizeSearchQuery(raw);
    if (!next) return;
    if (!query) { setShow("all"); setSort("relevance"); }
    setQuery(next);
    onChange?.();
    const target = pathWithSearch(window.location.pathname, next);
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.pushState(null, "", target);
  }, [onChange, query]);
  const clear = useCallback(() => {
    setQuery("");
    onChange?.();
    if (window.location.search.includes("q=")) window.history.replaceState(null, "", window.location.pathname);
  }, [onChange]);
  return { query, show, setShow, sort, setSort, searching, feed, submit, clear };
}
