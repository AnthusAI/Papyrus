"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  canonicalContentItemStage,
  legacyStageKeysToLoad,
  type ContentItemVersionRecord,
} from "../lib/content-item-lifecycle";
import { getContentItemStageDefinitions } from "../lib/site-brand";
import { applyChangedVersions, newestUpdatedAt } from "../lib/board-refresh";
import { storyStageIndexMode } from "../lib/story-stage-mode";
import { loadNewsroomContentItemStagePage, loadNewsroomContentItemsChangedSince } from "./news-desk-taxonomy-client";

const FAILED_PAGE_RETRY_DELAY_MILLISECONDS = 5_000;
const FAILED_PAGE_RETRY_LIMIT = 5;

type StageBucket = {
  versions: ContentItemVersionRecord[];
  nextToken: string | null;
  pagesLoaded: number;
};

export type PagedContentItemVersions = {
  versions: ContentItemVersionRecord[];
  loading: boolean;
  error: string | null;
  stageHasMore: (canonicalStage: string) => boolean;
  loadMoreForStage: (canonicalStage: string) => void;
  /** Ask each loaded stage only for rows changed since its newest row, and merge them in. The board's single timer calls this. */
  refresh: () => Promise<void>;
};

/**
 * Newest-updated content items per stage, one page per stage to start, more pages on demand.
 * A refresh asks each stage only for rows updated since the newest row it already holds (the stage index's sort key), so a quiet
 * board gets empty answers. The caller owns the timer.
 */
export function usePagedContentItemVersions(options: {
  enabled: boolean;
  openedCollapsedUntilOpenedStages: readonly string[];
}): PagedContentItemVersions {
  const { enabled, openedCollapsedUntilOpenedStages } = options;
  const [buckets, setBuckets] = useState<Record<string, StageBucket>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bucketsRef = useRef(buckets);
  const stageKeysBeingExtendedRef = useRef(new Set<string>());
  const generationRef = useRef(0);

  const openedStagesSignature = openedCollapsedUntilOpenedStages.join(",");
  const stageKeysToLoad = useMemo(() => {
    const stageDefinitions = getContentItemStageDefinitions();
    return [
      ...stageDefinitions
        .filter(definition => !definition.collapsedUntilOpened || openedStagesSignature.split(",").includes(definition.key))
        .map(definition => definition.key),
      ...legacyStageKeysToLoad(stageDefinitions),
    ];
  }, [openedStagesSignature]);
  const stageKeysToLoadRef = useRef(stageKeysToLoad);
  stageKeysToLoadRef.current = stageKeysToLoad;

  const storeBuckets = useCallback((update: (previous: Record<string, StageBucket>) => Record<string, StageBucket>) => {
    const next = update(bucketsRef.current);
    bucketsRef.current = next;
    setBuckets(next);
  }, []);

  const loadFirstPages = useCallback(async (request: number, isInitial: boolean, stageKeys: readonly string[]) => {
    if (isInitial) setLoading(true);
    try {
      const freshBuckets = await Promise.all(stageKeys.map(async stageKey => {
        const page = await loadNewsroomContentItemStagePage(stageKey);
        return [stageKey, { versions: page.versions, nextToken: page.nextToken, pagesLoaded: 1 }] as const;
      }));
      if (generationRef.current !== request) return;
      storeBuckets(previous => {
        const next = { ...previous };
        for (const [stageKey, fresh] of freshBuckets) next[stageKey] = fresh;
        return next;
      });
      setError(null);
    } catch (reason: unknown) {
      if (generationRef.current === request && isInitial) setError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
    } finally {
      if (generationRef.current === request && isInitial) setLoading(false);
    }
  }, [storeBuckets]);

  const refresh = useCallback(async () => {
    const request = generationRef.current;
    const stageKeys = stageKeysToLoadRef.current.filter(stageKey => stageKey in bucketsRef.current);
    try {
      const changed = await Promise.all(stageKeys.map(async stageKey => {
        const since = newestUpdatedAt(bucketsRef.current[stageKey].versions);
        const rows = since ? await loadNewsroomContentItemsChangedSince(stageKey, since) : (await loadNewsroomContentItemStagePage(stageKey)).versions;
        return [stageKey, rows] as const;
      }));
      if (generationRef.current !== request) return;
      storeBuckets(previous => applyChangedVersions(previous, Object.fromEntries(changed), { oneRowPerLineage: storyStageIndexMode() === "head" }));
    } catch {
      // A failed background refresh keeps what is shown; the next refresh tries again.
    }
  }, [storeBuckets]);

  useEffect(() => {
    const request = ++generationRef.current;
    bucketsRef.current = {};
    setBuckets({});
    setError(null);
    if (!enabled) { setLoading(false); return; }
    void loadFirstPages(request, true, stageKeysToLoadRef.current);
    return () => { generationRef.current = request + 1; };
  }, [enabled, loadFirstPages]);

  useEffect(() => {
    if (!enabled) return;
    const stageKeysNotLoadedYet = stageKeysToLoad.filter(stageKey => !(stageKey in bucketsRef.current));
    if (stageKeysNotLoadedYet.length) void loadFirstPages(generationRef.current, false, stageKeysNotLoadedYet);
  }, [enabled, loadFirstPages, stageKeysToLoad]);

  const stageKeysInCanonicalStage = useCallback((canonicalStage: string) => Object.keys(bucketsRef.current)
    .filter(stageKey => canonicalContentItemStage(stageKey, getContentItemStageDefinitions()) === canonicalStage), []);

  const requestNextPageForStage = useCallback((canonicalStage: string, failedAttempts: number) => {
    const request = generationRef.current;
    for (const stageKey of stageKeysInCanonicalStage(canonicalStage)) {
      const bucket = bucketsRef.current[stageKey];
      if (!bucket?.nextToken || stageKeysBeingExtendedRef.current.has(stageKey)) continue;
      stageKeysBeingExtendedRef.current.add(stageKey);
      loadNewsroomContentItemStagePage(stageKey, bucket.nextToken).then(page => {
        if (generationRef.current !== request) return;
        storeBuckets(previous => {
          const current = previous[stageKey] ?? bucket;
          const knownIds = new Set(current.versions.map(version => version.id));
          return {
            ...previous,
            [stageKey]: {
              versions: [...current.versions, ...page.versions.filter(version => !knownIds.has(version.id))],
              nextToken: page.nextToken,
              pagesLoaded: current.pagesLoaded + 1,
            },
          };
        });
      }).catch(() => {
        if (failedAttempts + 1 >= FAILED_PAGE_RETRY_LIMIT) return;
        window.setTimeout(() => {
          if (generationRef.current === request) requestNextPageForStage(canonicalStage, failedAttempts + 1);
        }, FAILED_PAGE_RETRY_DELAY_MILLISECONDS);
      }).finally(() => { stageKeysBeingExtendedRef.current.delete(stageKey); });
    }
  }, [stageKeysInCanonicalStage, storeBuckets]);

  const loadMoreForStage = useCallback((canonicalStage: string) => requestNextPageForStage(canonicalStage, 0), [requestNextPageForStage]);

  const stageHasMore = useCallback((canonicalStage: string) => stageKeysInCanonicalStage(canonicalStage)
    .some(stageKey => Boolean(bucketsRef.current[stageKey]?.nextToken)), [stageKeysInCanonicalStage]);

  const versions = useMemo(() => Object.values(buckets).flatMap(bucket => bucket.versions), [buckets]);
  return { versions, loading, error, stageHasMore, loadMoreForStage, refresh };
}
