"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { loadPredictionsForReferences, type PredictionStatus, type PredictionStatuses } from "./reference-predictions";

/**
 * Keeps a prediction status per Reference. `ids` are the References on screen; any id not yet read (and not being read) is read now,
 * so each newly shown page of the feed reads only its own. A failure is kept for that Reference alone and `retry(id)` reads it again.
 */
export function useReferencePredictions<Relation>({
  enabled,
  ids,
  load,
  onRelations,
}: {
  enabled: boolean;
  ids: readonly string[];
  load: (lineageId: string) => Promise<Relation[]>;
  onRelations: (lineageId: string, relations: Relation[]) => void;
}): { statuses: PredictionStatuses; retry: (lineageId: string) => void } {
  const [statuses, setStatuses] = useState<Map<string, PredictionStatus>>(() => new Map());
  const requested = useRef(new Set<string>());
  const live = useRef({ load, onRelations });
  live.current = { load, onRelations };
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const read = useCallback((batch: string[]) => {
    if (!batch.length) return;
    setStatuses((current) => {
      const next = new Map(current);
      for (const id of batch) next.set(id, { state: "loading" });
      return next;
    });
    const settle = (id: string, status: PredictionStatus) => {
      if (mounted.current) setStatuses((current) => new Map(current).set(id, status));
    };
    void loadPredictionsForReferences(batch, (id) => live.current.load(id), {
      ready: (id, relations) => { if (mounted.current) live.current.onRelations(id, relations); settle(id, { state: "ready" }); },
      failed: (id, error) => settle(id, { state: "error", error }),
    });
  }, []);

  const key = ids.join("\u0000");
  useEffect(() => {
    if (!enabled) return;
    const fresh = ids.filter((id) => !requested.current.has(id));
    for (const id of fresh) requested.current.add(id);
    read(fresh);
    // `key` stands for `ids`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key, read]);

  const retry = useCallback((lineageId: string) => read([lineageId]), [read]);
  return { statuses, retry };
}
