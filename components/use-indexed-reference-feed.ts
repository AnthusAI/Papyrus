"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import {
  FEED_READ_PAGE_SIZE,
  MergedFeedReader,
  feedStateKeys,
  type FeedStreamReader,
  type FeedStreamShow,
  type FeedStreamSort,
} from "../lib/reference-feed-pages";

export type IndexedFeedSource = {
  /** The corpora whose partitions are read (a site can have several). */
  loadCorpusIds: () => Promise<string[]>;
  /** One page of one partition from the feed-state index. */
  readStream: FeedStreamReader;
};

type Status = "idle" | "loading" | "ready" | "error";

/**
 * The References feed, a page at a time from the feed-state indexes, in the order the index gives (merged across corpora).
 * The first page is one round of reads; `loadMore` reads one more round when the reader nears the end. Nothing else is read.
 * A failed first read leaves `status` at "error" with a sentence and `retry` reads it again; a failed later page keeps the cards already
 * shown and sets `moreError`.
 */
export function useIndexedReferenceFeed({
  enabled,
  source,
  sort,
  show,
  pageSize = FEED_READ_PAGE_SIZE,
}: {
  enabled: boolean;
  source: IndexedFeedSource | undefined;
  sort: FeedStreamSort;
  show: FeedStreamShow;
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
      const next = new MergedFeedReader({ keys: feedStateKeys(corpusIds, show), sort, read: current.readStream, pageSize });
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
  }, [pageSize, show, sort]);

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
