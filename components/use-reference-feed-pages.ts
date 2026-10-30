"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { ReferenceFeedController, type FeedState } from "../lib/reference-feed-controller";
import type { ReferenceFeedSource } from "../lib/reference-feed-pages";
import type { FeedShow, FeedSort } from "../lib/reference-feed-ranking";

/**
 * The References feed for one visit, paged: the controller (lib/reference-feed-controller.ts) behind React. A new `source` is a new visit.
 * It loads the first page for the chosen sort and show, more on request, and checks for new arrivals whenever the tab regains focus.
 */
export function useReferenceFeedPages({ source, sort, show, enabled = true }: {
  source: ReferenceFeedSource;
  sort: FeedSort;
  show: FeedShow;
  enabled?: boolean;
}): { controller: ReferenceFeedController; state: FeedState } {
  const controller = useMemo(() => new ReferenceFeedController(source), [source]);
  const state = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);
  useEffect(() => {
    if (enabled) controller.activate(sort, show);
  }, [controller, enabled, sort, show]);
  useEffect(() => {
    if (!enabled) return;
    const check = () => { if (document.visibilityState !== "hidden") void controller.checkNew(); };
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [controller, enabled]);
  return { controller, state };
}
