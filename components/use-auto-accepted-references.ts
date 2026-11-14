"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import { AUTO_ACCEPTED_PAGE_SIZE, type AutoAcceptedPage } from "../lib/auto-accepted-references";

export type AutoAcceptedReader = (options: { nextToken?: string | null; limit?: number }) => Promise<AutoAcceptedPage>;

/**
 * The pages of the "Accepted automatically" list, read from the database a page at a time (newest first) while the filter is open.
 * Nothing is read until `enabled`, so the other filters cost nothing. `loadMore` reads the next page; a failure is kept as a sentence and
 * `retry` reads again. A Reference an editor then Rejects leaves the list on its own (the page hides rejected records), so this only has to
 * keep what the database returned.
 */
export function useAutoAcceptedReferences({ enabled, read }: { enabled: boolean; read: AutoAcceptedReader }) {
  const [items, setItems] = useState<ReferenceRecord[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "loadingMore" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [nextToken, setNextToken] = useState<string | null>(null);
  const generation = useRef(0);
  const readRef = useRef(read);
  readRef.current = read;

  const load = useCallback(async (token: string | null) => {
    const mine = ++generation.current;
    setState(token ? "loadingMore" : "loading");
    setError(null);
    try {
      const page = await readRef.current({ nextToken: token, limit: AUTO_ACCEPTED_PAGE_SIZE });
      if (mine !== generation.current) return;
      setItems((current) => {
        if (!token) return page.items;
        const known = new Set(current.map((item) => item.id));
        return [...current, ...page.items.filter((item) => !known.has(item.id))];
      });
      setNextToken(page.nextToken);
      setState("ready");
    } catch (failure) {
      if (mine !== generation.current) return;
      setError(failure instanceof Error && failure.message ? failure.message : "The list could not be read.");
      setState("error");
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      generation.current += 1;
      return;
    }
    void load(null);
    return () => { generation.current += 1; };
  }, [enabled, load]);

  return {
    items,
    loading: state === "loading" || (enabled && state === "idle"),
    loadingMore: state === "loadingMore",
    error,
    hasMore: Boolean(nextToken),
    loadMore: useCallback(() => { if (nextToken && state !== "loadingMore" && state !== "loading") void load(nextToken); }, [load, nextToken, state]),
    retry: useCallback(() => { void load(state === "error" && items.length ? nextToken : null); }, [items.length, load, nextToken, state]),
  };
}
