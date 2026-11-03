"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { RatingFeedback } from "./decision-control";

/** Saves a Story's rating: any version id of the Story, and 1 to 5 or null to clear. Throws a sentence when it cannot. */
export type SaveStoryStars = (itemId: string, stars: number | null) => Promise<void>;

/**
 * One store for the star ratings of every Story on a surface, so the board card, the drawer and the editor of one Story show the same rating at once.
 * It is keyed by the Story's lineage id. A tap is optimistic; a failed save puts the saved rating back and says it was not saved. The record the
 * surface read stays the truth otherwise: a rating set here is honoured until the record shows something that is neither the old nor the new value.
 */
export type StoryStarsController = {
  /** The rating to show: what was tapped here and saved or saving, else the record's. */
  value: (lineageId: string, saved: number | null) => number | null;
  feedback: (lineageId: string) => RatingFeedback;
  /** Tap a star; tapping the star already chosen clears the rating. One save at a time per Story. */
  tap: (lineageId: string, itemId: string, saved: number | null, tapped: number) => void;
};

type Touched = { value: number | null; basedOn: number | null };

export function useStoryStars(save: SaveStoryStars): StoryStarsController {
  const [touched, setTouched] = useState<Record<string, Touched>>({});
  const [feedbackByStory, setFeedback] = useState<Record<string, RatingFeedback>>({});
  const touchedRef = useRef(touched);
  const inFlight = useRef(new Set<string>());
  const latestSave = useRef(save);
  latestSave.current = save;

  const value = useCallback((lineageId: string, saved: number | null): number | null => {
    const mine = touched[lineageId];
    if (!mine) return saved;
    // The record moved on (another editor, a refresh): neither what we based the tap on nor what we set.
    if (saved !== mine.basedOn && saved !== mine.value) return saved;
    return mine.value;
  }, [touched]);

  const feedback = useCallback((lineageId: string): RatingFeedback => feedbackByStory[lineageId] ?? { phase: "idle" }, [feedbackByStory]);

  const tap = useCallback((lineageId: string, itemId: string, saved: number | null, tapped: number) => {
    if (inFlight.current.has(lineageId)) return;
    const mine = touchedRef.current[lineageId];
    const shown = mine && (saved === mine.basedOn || saved === mine.value) ? mine.value : saved;
    const next = shown === tapped ? null : tapped;
    inFlight.current.add(lineageId);
    const withTouch = { ...touchedRef.current, [lineageId]: { value: next, basedOn: saved } };
    touchedRef.current = withTouch;
    setTouched(withTouch);
    setFeedback((previous) => ({ ...previous, [lineageId]: { phase: "saving" } }));
    void (async () => {
      try {
        await latestSave.current(itemId, next);
        setFeedback((previous) => ({ ...previous, [lineageId]: { phase: "saved" } }));
      } catch (failure) {
        const { [lineageId]: _undone, ...rest } = touchedRef.current;
        touchedRef.current = rest;
        setTouched(rest);
        setFeedback((previous) => ({ ...previous, [lineageId]: { phase: "error", message: failure instanceof Error ? failure.message : "Your rating could not be saved. Tap a star to try again." } }));
      } finally {
        inFlight.current.delete(lineageId);
      }
    })();
  }, []);

  return useMemo(() => ({ value, feedback, tap }), [value, feedback, tap]);
}
