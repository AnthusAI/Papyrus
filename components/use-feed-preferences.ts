"use client";

import { useCallback, useEffect, useState } from "react";
import { DEFAULT_FEED_SHOW, DEFAULT_FEED_SORT, type FeedShow, type FeedSort } from "../lib/reference-feed-ranking";

const SORT_KEY = "papyrus:reference-feed:sort";
const SHOW_KEY = "papyrus:reference-feed:show";

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

/** The viewer's Sort and Show choices, remembered in this browser. The page renders with the defaults, then applies what was saved. */
export function useFeedPreferences() {
  const [sort, setSortState] = useState<FeedSort>(DEFAULT_FEED_SORT);
  const [show, setShowState] = useState<FeedShow>(DEFAULT_FEED_SHOW);
  useEffect(() => {
    setSortState(read<FeedSort>(SORT_KEY, ["best", "newest"], DEFAULT_FEED_SORT));
    setShowState(read<FeedShow>(SHOW_KEY, ["unrated", "all"], DEFAULT_FEED_SHOW));
  }, []);
  const setSort = useCallback((next: FeedSort) => { setSortState(next); write(SORT_KEY, next); }, []);
  const setShow = useCallback((next: FeedShow) => { setShowState(next); write(SHOW_KEY, next); }, []);
  return { sort, setSort, show, setShow };
}
