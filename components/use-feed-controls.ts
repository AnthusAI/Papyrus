"use client";

import { useCallback } from "react";
import type { FeedMinStars, FeedShow, FeedSort } from "../lib/reference-feed-ranking";
import type { ReferenceSearchReader, ReferenceSearchShow, ReferenceSearchSort } from "../lib/reference-search";
import { useFeedPreferences } from "./use-feed-preferences";
import { useFeedSearch } from "./use-indexed-reference-feed";

/**
 * The feed's Sort, Show and Minimum stars controls, with and without a search open. Without one they are the saved choices. While a search is open
 * Sort reads Relevance, Newest or Quality (the search's own, opened on Relevance, not saved) and Show is the search's (opened on All, not saved), and
 * the minimum of stars is the saved one, shared with the feed. The rules between the choices (`choose` in use-feed-preferences.ts) hold in both: a
 * minimum or Quality moves an Unrated Show to All, and a minimum moves a saved Best bets to Newest.
 */
export function useFeedControls({ searchRead, onChange }: { searchRead: ReferenceSearchReader | undefined; onChange?: () => void }) {
  const prefs = useFeedPreferences();
  const search = useFeedSearch({ enabled: Boolean(searchRead), read: searchRead, onChange, minStars: prefs.minStars });
  const { searching } = search;
  const { setSort: setSavedSort, setShow: setSavedShow, setMinStars: setSavedMinStars } = prefs;
  const { setSort: setSearchSort, setShow: setSearchShow, show: searchShow } = search;
  const sort: FeedSort | ReferenceSearchSort = searching ? search.sort : prefs.sort;
  const show: FeedShow | ReferenceSearchShow = searching ? searchShow : prefs.show;
  const setSort = useCallback((next: FeedSort | ReferenceSearchSort) => {
    if (!searching) { if (next !== "relevance") setSavedSort(next); return; }
    if (next === "best") return;
    if (next === "quality" && searchShow === "unrated") setSearchShow("all");
    setSearchSort(next);
  }, [searching, searchShow, setSavedSort, setSearchShow, setSearchSort]);
  const setShow = useCallback((next: FeedShow | ReferenceSearchShow) => { if (searching) setSearchShow(next); else setSavedShow(next); }, [searching, setSavedShow, setSearchShow]);
  const setMinStars = useCallback((next: FeedMinStars) => {
    setSavedMinStars(next);
    if (searching && next !== 0 && searchShow === "unrated") setSearchShow("all");
  }, [searching, searchShow, setSavedMinStars, setSearchShow]);
  return { sort, setSort, show, setShow, minStars: prefs.minStars, setMinStars, saved: prefs, search };
}
