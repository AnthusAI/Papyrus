"use client";

import { useCallback, useEffect, useState } from "react";

/** Load persisted predictions and attributed review history without cancelling on a loading rerender. */
export function useReferenceReviewData<Relation, Message>({
  enabled,
  loadRelations,
  loadMessages,
  onRelations,
  onMessages,
}: {
  enabled: boolean;
  /** Optional: the References feed reads predictions per Reference instead. */
  loadRelations?: () => Promise<Relation[]>;
  loadMessages: () => Promise<Message[]>;
  onRelations?: (relations: Relation[]) => void;
  onMessages: (messages: Message[]) => void;
}) {
  const [state, setState] = useState<"loading" | "ready" | "error">(enabled ? "loading" : "ready");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((current) => current + 1), []);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    setState("loading");
    setError(null);
    void Promise.allSettled([loadRelations ? loadRelations() : Promise.resolve([] as Relation[]), loadMessages()]).then(([relations, history]) => {
      if (!active) return;
      if (relations.status === "fulfilled" && onRelations) onRelations(relations.value);
      if (history.status === "fulfilled") onMessages(history.value);
      const failure = relations.status === "rejected" ? relations.reason : history.status === "rejected" ? history.reason : null;
      if (failure) {
        const subject = relations.status === "rejected" ? "Predictions" : "Review history";
        setError(`${subject} could not be loaded. ${failure instanceof Error ? failure.message : "Try again."}`);
        setState("error");
      } else {
        setState("ready");
      }
    });
    return () => { active = false; };
  }, [enabled, loadRelations, loadMessages, onRelations, onMessages, attempt]);
  return { state, error, retry };
}
