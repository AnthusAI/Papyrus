"use client";

import { useCallback, useEffect, useState } from "react";
import type { FeedCaptured, FeedMinStars, FeedShow, FeedSort } from "../lib/reference-feed-ranking";
import type { ReferenceSearchReader, ReferenceSearchShow, ReferenceSearchSort } from "../lib/reference-search";
import { choose, useFeedPreferences, type FeedChoices } from "./use-feed-preferences";
import { feedChoicesFromSearch } from "../lib/reference-feed-view";
import { useFeedSearch } from "./use-indexed-reference-feed";

/**
 * The feed's Sort, Reviewed (`show`), Minimum stars and Captured controls, with and without a search open. Without one they are the saved choices. While a search is open
 * Sort reads Relevance, Newest or Quality (the search's own, opened on Relevance, not saved) and Reviewed is the search's (opened on Any, not saved), and
 * the minimum of stars and Captured are the saved ones, shared with the feed. The rules between the choices (`choose` in use-feed-preferences.ts) hold in both: a
 * minimum or Quality moves a Reviewed No to Any, and a minimum moves a saved Predictions to Newest.
 *
 * A page address can open the feed on choices of its own (`/newsroom/references?reviewed=accepted&captured=no&sort=newest`, see
 * `feedChoicesFromSearch`): the home page's "See all" for accepted References that still need a person to capture them. Those choices are a
 * view for this visit. They are never written to the saved choices, and changing a control while one is open changes the view, not the saved choices.
 */
export function useFeedControls({ searchRead, onChange }: { searchRead: ReferenceSearchReader | undefined; onChange?: () => void }) {
  const prefs = useFeedPreferences();
  const [adHoc, setAdHoc] = useState<Partial<FeedChoices> | null>(null);
  useEffect(() => { setAdHoc(feedChoicesFromSearch(window.location.search)); }, []);
  const choices: FeedChoices = { sort: prefs.sort, show: prefs.show, minStars: prefs.minStars, captured: prefs.captured, ...(adHoc ?? {}) };
  const { change: changeSaved } = prefs;
  const [viewChoices, setViewChoices] = useState<FeedChoices | null>(null);
  // `viewChoices` is the whole view once a control is changed while an address-chosen view is open.
  const effective: FeedChoices = adHoc ? viewChoices ?? choices : choices;
  const change = useCallback((next: Partial<FeedChoices>) => {
    if (adHoc) setViewChoices((current) => choose(current ?? effective, next));
    else changeSaved(next);
  }, [adHoc, changeSaved, effective]);

  const search = useFeedSearch({ enabled: Boolean(searchRead), read: searchRead, onChange, minStars: effective.minStars, captured: effective.captured });
  const { searching } = search;
  const { setSort: setSearchSort, setShow: setSearchShow, show: searchShow } = search;
  const sort: FeedSort | ReferenceSearchSort = searching ? search.sort : effective.sort;
  const show: FeedShow | ReferenceSearchShow = searching ? searchShow : effective.show;
  const setSort = useCallback((next: FeedSort | ReferenceSearchSort) => {
    if (!searching) { if (next !== "relevance") change({ sort: next }); return; }
    if (next === "best") return;
    if (next === "quality" && searchShow === "unrated") setSearchShow("all");
    setSearchSort(next);
  }, [change, searching, searchShow, setSearchShow, setSearchSort]);
  const setShow = useCallback((next: FeedShow | ReferenceSearchShow) => { if (searching) setSearchShow(next); else change({ show: next }); }, [change, searching, setSearchShow]);
  const setMinStars = useCallback((next: FeedMinStars) => {
    change({ minStars: next });
    if (searching && next !== 0 && searchShow === "unrated") setSearchShow("all");
  }, [change, searching, searchShow, setSearchShow]);
  const setCaptured = useCallback((next: FeedCaptured) => change({ captured: next }), [change]);
  return { sort, setSort, show, setShow, minStars: effective.minStars, setMinStars, captured: effective.captured, setCaptured, saved: effective, search };
}
