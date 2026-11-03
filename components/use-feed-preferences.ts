"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_FEED_MIN_STARS,
  DEFAULT_FEED_SHOW,
  DEFAULT_FEED_SORT,
  FEED_MIN_STARS,
  type FeedMinStars,
  type FeedShow,
  type FeedSort,
} from "../lib/reference-feed-ranking";

const SORT_KEY = "papyrus:reference-feed:sort";
const SHOW_KEY = "papyrus:reference-feed:show";
const MIN_STARS_KEY = "papyrus:reference-feed:min-stars";

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = window.localStorage.getItem(key);
    return allowed.includes(stored as T) ? (stored as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: string) {
  try { window.localStorage.setItem(key, value); } catch { /* The choice still works for this visit without storage. */ }
}

export type FeedChoices = { sort: FeedSort; show: FeedShow; minStars: FeedMinStars };

/**
 * What one choice does to the others, so the list never looks empty for a reason the editor cannot see. Stars are separate from the vote, so most
 * starred References are voted: Quality and a minimum move Show from Unrated to All. The star index is by arrival and cannot order by prediction:
 * a minimum moves Predictions to Newest, and Predictions takes the minimum back to Any. Show stays the editor's: picking it afterwards is honoured.
 */
export function choose(current: FeedChoices, change: Partial<FeedChoices>): FeedChoices {
  const next = { ...current, ...change };
  if (change.sort === "best") next.minStars = 0;
  if ((change.sort === "quality" || (change.minStars !== undefined && change.minStars !== 0)) && change.show === undefined && next.show === "unrated") next.show = "all";
  if (change.minStars !== undefined && change.minStars !== 0 && change.sort === undefined && next.sort === "best") next.sort = "newest";
  return next;
}

/** The viewer's Sort, Show and Minimum stars choices, remembered in this browser. The page renders with the defaults, then applies what was saved. */
export function useFeedPreferences() {
  const [choices, setChoices] = useState<FeedChoices>({ sort: DEFAULT_FEED_SORT, show: DEFAULT_FEED_SHOW, minStars: DEFAULT_FEED_MIN_STARS });
  useEffect(() => {
    const stored = read<string>(MIN_STARS_KEY, FEED_MIN_STARS.map(String), String(DEFAULT_FEED_MIN_STARS));
    setChoices({
      sort: read<FeedSort>(SORT_KEY, ["best", "newest", "quality"], DEFAULT_FEED_SORT),
      show: read<FeedShow>(SHOW_KEY, ["unrated", "all", "rated"], DEFAULT_FEED_SHOW),
      minStars: Number(stored) as FeedMinStars,
    });
  }, []);
  const change = useCallback((change: Partial<FeedChoices>) => {
    setChoices((current) => {
      const next = choose(current, change);
      if (next.sort !== current.sort) write(SORT_KEY, next.sort);
      if (next.show !== current.show) write(SHOW_KEY, next.show);
      if (next.minStars !== current.minStars) write(MIN_STARS_KEY, String(next.minStars));
      return next;
    });
  }, []);
  const setSort = useCallback((sort: FeedSort) => change({ sort }), [change]);
  const setShow = useCallback((show: FeedShow) => change({ show }), [change]);
  const setMinStars = useCallback((minStars: FeedMinStars) => change({ minStars }), [change]);
  return { sort: choices.sort, setSort, show: choices.show, setShow, minStars: choices.minStars, setMinStars };
}
