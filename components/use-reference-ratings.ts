"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReferenceRejectionReasonCode } from "../lib/reference-policy";
import type { ReviewChoice } from "./reference-review-card";
import type { RatingFeedback } from "./review-rating-grid";

/** How long after the last keystroke a typed reason is saved on its own. */
export const NOTE_AUTOSAVE_MS = 1200;

export type ItemRating = {
  /** The reason as typed, else as saved. In the store itself it stays undefined until touched, so an untouched field follows the record. */
  note?: string;
  reasonCode?: ReferenceRejectionReasonCode | null;
  /** A vote that is waiting for a reason (Reject needs one) or is still saving. */
  pending: ReviewChoice | null;
  /** True while a Reject is waiting for its reason. */
  askReason: boolean;
  feedback: RatingFeedback;
};

const EMPTY: ItemRating = { pending: null, askReason: false, feedback: { phase: "idle" } };

export type RatingSave = (id: string, choice: ReviewChoice, detail: { note: string; reasonCode: ReferenceRejectionReasonCode | null }) => Promise<void> | void;

export type RatingController = {
  get: (id: string) => ItemRating;
  choose: (id: string, choice: ReviewChoice) => void;
  setReason: (id: string, code: ReferenceRejectionReasonCode) => void;
  setNote: (id: string, text: string) => void;
  /** Save a typed reason now (on blur). */
  commitNote: (id: string) => void;
  cancelReason: (id: string) => void;
};

/**
 * One store for the rating state of every item, shared by the grid card and the detail pane so a vote or a reason typed in either
 * shows in both at once. `saved(id)` is the saved human answer; `seed(id)` the saved note and reason code.
 *   vote, then reason  -> the reason is saved onto the existing decision (on blur, or after a short pause)
 *   reason, then vote  -> the vote carries the reason
 * A Reject needs a reason code (the backend refuses one without), so it waits as `pending` until one is chosen; a typed reason is
 * kept in the store until it is saved and is never dropped by a failed save.
 */
export function useRatingStore({ save, saved, seed, needsReason }: {
  save: RatingSave;
  saved: (id: string) => ReviewChoice | null;
  seed: (id: string) => { note: string; reasonCode: ReferenceRejectionReasonCode | null };
  /** Whether a Reject on this item must wait for a reason code. Default yes (a Reference); an AI draft or an email asks nothing. */
  needsReason?: (id: string) => boolean;
}): RatingController {
  const [items, setItems] = useState<Record<string, ItemRating>>({});
  const itemsRef = useRef(items);
  const latest = useRef({ save, saved, seed, needsReason });
  latest.current = { save, saved, seed, needsReason };
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const inFlight = useRef<Set<string>>(new Set());
  const dirty = useRef<Set<string>>(new Set());

  const patch = useCallback((id: string, change: Partial<ItemRating>) => {
    const next = { ...itemsRef.current, [id]: { ...(itemsRef.current[id] ?? EMPTY), ...change } };
    itemsRef.current = next;
    setItems(next);
  }, []);

  // What a reader of the store sees: the touched value, else what is saved. (A saved reason therefore shows on the card too.)
  const get = useCallback((id: string): ItemRating => {
    const item = items[id] ?? EMPTY;
    const seeded = latest.current.seed(id);
    return { ...item, note: item.note ?? seeded.note, reasonCode: item.reasonCode !== undefined ? item.reasonCode : seeded.reasonCode };
  }, [items]);

  const values = (id: string) => {
    const item = itemsRef.current[id] ?? EMPTY;
    const seeded = latest.current.seed(id);
    return { note: item.note ?? seeded.note, reasonCode: item.reasonCode !== undefined ? item.reasonCode : seeded.reasonCode };
  };

  const commit = useCallback(async (id: string, choice: ReviewChoice) => {
    const { note, reasonCode } = values(id);
    if (choice === "reject" && !reasonCode && (latest.current.needsReason?.(id) ?? true)) { patch(id, { pending: "reject", askReason: true }); return; }
    if (inFlight.current.has(id)) { dirty.current.add(id); return; }
    inFlight.current.add(id);
    dirty.current.delete(id);
    const started = itemsRef.current[id] ?? EMPTY;
    patch(id, { pending: choice, askReason: false, feedback: { phase: "saving" } });
    try {
      await latest.current.save(id, choice, { note: note.trim(), reasonCode: choice === "reject" ? reasonCode : null });
      // What was saved now follows the record again (another editor's update shows); anything typed meanwhile is kept.
      const now = itemsRef.current[id] ?? EMPTY;
      patch(id, { pending: null, feedback: { phase: "saved" }, ...(now.note === started.note ? { note: undefined } : {}), ...(now.reasonCode === started.reasonCode ? { reasonCode: undefined } : {}) });
    } catch (failure) {
      // The typed reason stays in the store; only the vote is undone.
      patch(id, { pending: null, feedback: { phase: "error", message: failure instanceof Error ? failure.message : "Your answer could not be saved. Tap it again to retry." } });
    } finally {
      inFlight.current.delete(id);
    }
    if (dirty.current.has(id)) { dirty.current.delete(id); const again = itemsRef.current[id]?.pending ?? latest.current.saved(id); if (again) void commit(id, again); }
  }, [patch]);

  const effective = (id: string): ReviewChoice | null => itemsRef.current[id]?.pending ?? latest.current.saved(id);

  const choose = useCallback((id: string, choice: ReviewChoice) => {
    if (effective(id) === choice && !itemsRef.current[id]?.askReason) return; // the chosen answer never unselects itself
    void commit(id, choice);
  }, [commit]);

  const setReason = useCallback((id: string, code: ReferenceRejectionReasonCode) => {
    patch(id, { reasonCode: code });
    // Vote then reason: onto the existing (or waiting) decision. Reason then vote: stored, and the vote carries it.
    if (effective(id) === "reject") void commit(id, "reject");
  }, [commit, patch]);

  const setNote = useCallback((id: string, text: string) => {
    patch(id, { note: text, feedback: { phase: "idle" } });
    dirty.current.add(`note:${id}`);
    clearTimeout(timers.current[id]);
    timers.current[id] = setTimeout(() => {
      const choice = effective(id);
      if (choice && dirty.current.delete(`note:${id}`)) void commit(id, choice);
    }, NOTE_AUTOSAVE_MS);
  }, [commit, patch]);

  const commitNote = useCallback((id: string) => {
    clearTimeout(timers.current[id]);
    const choice = effective(id);
    if (choice && dirty.current.delete(`note:${id}`)) void commit(id, choice);
  }, [commit]);

  const cancelReason = useCallback((id: string) => patch(id, { pending: null, askReason: false }), [patch]);

  useEffect(() => () => { for (const timer of Object.values(timers.current)) clearTimeout(timer); }, []);

  return { get, choose, setReason, setNote, commitNote, cancelReason };
}
