"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyFeedOrderSnapshot,
  extendFeedOrderSnapshot,
  feedLeadId,
  feedWindow,
  olderThanSnapshot,
  takeFeedOrderSnapshot,
  visibleFeedItems,
  type FeedItem,
  type FeedOrderSnapshot,
  type FeedShow,
  type FeedSort,
} from "../lib/reference-feed-ranking";
import { predictionsSettled, type PredictionStatuses } from "../lib/reference-predictions";

/**
 * The feed's page of References, and the order they are shown in.
 *
 * Only the newest pages are on screen, and `onRequestPredictions` is told which References those are, so predictions are read for them
 * alone. Scrolling to the end (`loadMore`) adds the next page; its cards join once their predictions have settled, after everything
 * already placed, so nothing above moves. The order is taken ONCE per visit when the first page has settled and then left alone:
 * selecting, rating, a background refresh or a cache revalidation never re-rank it. Items that arrive later wait behind a "new items" pill.
 *
 * Without `predictionStatuses` (a page that has its predictions already) nothing waits on a prediction read.
 */
export function useFeedWindow({
  allItems,
  blocked,
  predictionStatuses,
  predictionsPending = false,
  onRequestPredictions,
  sort,
  show,
  visitRated,
}: {
  allItems: FeedItem[];
  /** True while the References themselves are not ready to be ordered (still loading, a saved copy, a preview skeleton). */
  blocked: boolean;
  predictionStatuses?: PredictionStatuses | undefined;
  /** When the page does not read per Reference: true while its one prediction read is still going. */
  predictionsPending?: boolean;
  onRequestPredictions?: ((lineageIds: string[]) => void) | undefined;
  sort: FeedSort;
  show: FeedShow;
  visitRated: ReadonlySet<string>;
}) {
  const [pages, setPages] = useState(1);
  const windowItems = useMemo(() => feedWindow(allItems, pages), [allItems, pages]);
  const windowIds = useMemo(() => windowItems.map((item) => item.lineageId), [windowItems]);
  const windowKey = windowIds.join("\u0000");
  useEffect(() => {
    if (!blocked) onRequestPredictions?.(windowIds);
    // `windowKey` stands for `windowIds`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowKey, onRequestPredictions, blocked]);

  const managed = Boolean(predictionStatuses);
  const settled = (id: string) => !predictionStatuses || predictionsSettled([id], predictionStatuses);
  const snapshot = useRef<FeedOrderSnapshot | null>(null);
  const [, bump] = useState(0);
  const ready = !blocked && allItems.length > 0 && (managed ? windowIds.every(settled) : !predictionsPending);
  if (!snapshot.current && ready) snapshot.current = takeFeedOrderSnapshot(windowItems);

  let pendingOlder: FeedItem[] = [];
  if (snapshot.current) {
    const older = olderThanSnapshot(snapshot.current, windowItems);
    const arrived = older.filter((item) => settled(item.lineageId));
    if (arrived.length) snapshot.current = extendFeedOrderSnapshot(snapshot.current, arrived);
    pendingOlder = older.filter((item) => !settled(item.lineageId));
  }
  const pendingIds = new Set(pendingOlder.map((item) => item.lineageId));
  const inWindow = new Set(windowIds);
  const live = allItems.filter((item) => (inWindow.has(item.lineageId) || snapshot.current?.known.has(item.lineageId)) && !pendingIds.has(item.lineageId));

  const stable = snapshot.current ? applyFeedOrderSnapshot(snapshot.current, live, sort, show) : null;
  const unstable = useMemo(() => visibleFeedItems(live, sort, show, visitRated), [live, sort, show, visitRated]);
  const items = stable?.items ?? unstable;
  return {
    items,
    leadId: stable ? stable.leadId : feedLeadId(items),
    newCount: stable?.newCount ?? 0,
    hasMore: windowItems.length < allItems.length,
    loadingMore: pendingOlder.length > 0,
    loadMore: useCallback(() => setPages((current) => current + 1), []),
    showNewItems: () => { snapshot.current = takeFeedOrderSnapshot(live); bump((count) => count + 1); },
    windowIds,
  };
}
