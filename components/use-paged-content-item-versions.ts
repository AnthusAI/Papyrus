"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  canonicalContentItemStage,
  legacyStageKeysToLoad,
  type ContentItemVersionRecord,
} from "../lib/content-item-lifecycle";
import { getContentItemStageDefinitions } from "../lib/site-brand";
import { loadNewsroomContentItemStagePage } from "./news-desk-taxonomy-client";

const REFRESH_INTERVAL_MILLISECONDS = 30_000;

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
};

function mergeFreshFirstPage(existing: StageBucket | undefined, fresh: StageBucket): StageBucket {
  if (!existing || existing.pagesLoaded <= 1) return fresh;
  const freshIds = new Set(fresh.versions.map(version => version.id));
  return {
    versions: [...fresh.versions, ...existing.versions.filter(version => !freshIds.has(version.id))],
    nextToken: existing.nextToken,
    pagesLoaded: existing.pagesLoaded,
  };
}

/**
 * Newest-updated content items per stage, one page per stage to start, more pages on demand.
 * The periodic refresh re-fetches only first pages and keeps whatever later pages were already loaded.
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

  const refreshFirstPages = useCallback(async (request: number, isInitial: boolean, stageKeys: readonly string[]) => {
    if (isInitial) setLoading(true);
    try {
      const freshBuckets = await Promise.all(stageKeys.map(async stageKey => {
        const page = await loadNewsroomContentItemStagePage(stageKey);
        return [stageKey, { versions: page.versions, nextToken: page.nextToken, pagesLoaded: 1 }] as const;
      }));
      if (generationRef.current !== request) return;
      storeBuckets(previous => {
        const next = { ...previous };
        for (const [stageKey, fresh] of freshBuckets) next[stageKey] = mergeFreshFirstPage(previous[stageKey], fresh);
        return next;
      });
      setError(null);
    } catch (reason: unknown) {
      if (generationRef.current === request && isInitial) setError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
    } finally {
      if (generationRef.current === request && isInitial) setLoading(false);
    }
  }, [storeBuckets]);

  useEffect(() => {
    const request = ++generationRef.current;
    bucketsRef.current = {};
    setBuckets({});
    setError(null);
    if (!enabled) { setLoading(false); return; }
    void refreshFirstPages(request, true, stageKeysToLoadRef.current);
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refreshFirstPages(request, false, stageKeysToLoadRef.current);
    };
    const interval = window.setInterval(refreshWhenVisible, REFRESH_INTERVAL_MILLISECONDS);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      generationRef.current = request + 1;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [enabled, refreshFirstPages]);

  useEffect(() => {
    if (!enabled) return;
    const stageKeysNotLoadedYet = stageKeysToLoad.filter(stageKey => !(stageKey in bucketsRef.current));
    if (stageKeysNotLoadedYet.length) void refreshFirstPages(generationRef.current, false, stageKeysNotLoadedYet);
  }, [enabled, refreshFirstPages, stageKeysToLoad]);

  const stageKeysInCanonicalStage = useCallback((canonicalStage: string) => Object.keys(bucketsRef.current)
    .filter(stageKey => canonicalContentItemStage(stageKey, getContentItemStageDefinitions()) === canonicalStage), []);

  const loadMoreForStage = useCallback((canonicalStage: string) => {
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
      }).catch(() => undefined).finally(() => { stageKeysBeingExtendedRef.current.delete(stageKey); });
    }
  }, [stageKeysInCanonicalStage, storeBuckets]);

  const stageHasMore = useCallback((canonicalStage: string) => stageKeysInCanonicalStage(canonicalStage)
    .some(stageKey => Boolean(bucketsRef.current[stageKey]?.nextToken)), [stageKeysInCanonicalStage]);

  const versions = useMemo(() => Object.values(buckets).flatMap(bucket => bucket.versions), [buckets]);
  return { versions, loading, error, stageHasMore, loadMoreForStage };
}
