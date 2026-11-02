"use client";

import { Loader2Icon, StarIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RatingFeedback } from "./decision-control";

const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";

export const STAR_COUNT = 5;

/** The words for a rating, for a screen reader and the status line. */
export function starsWords(stars: number | null): string {
  return stars ? `${stars} of ${STAR_COUNT} stars` : "No stars";
}

/**
 * An editor's optional interest in an item, one to five stars, beside Accept and Reject.
 *
 * One tap sets the rating, a tap on the star already chosen clears it. It is quick on purpose: five large targets in one row, no menu, no reason.
 * Filled and empty read by SHAPE (a solid star against an outline), never by colour alone, because some editors are colourblind; the count is
 * also written beside the stars. Stars are interest, not a vote: they leave Accept and Reject as they were.
 */
export function StarRating({
  disabled = false,
  feedback = { phase: "idle" },
  onChange,
  size = "compact",
  value,
}: {
  disabled?: boolean;
  feedback?: RatingFeedback;
  /** Called with the star that was tapped; the caller clears when it is the one already set. */
  onChange: (stars: number) => void;
  size?: "compact" | "large";
  value: number | null;
}) {
  const cell = size === "large" ? "min-h-12" : "min-h-10";
  return (
    <div className="grid gap-y-1" data-star-rating data-stars={value ?? 0}>
      <div className="flex items-center justify-between gap-2">
        <span className={cn(LABEL, "text-muted-foreground")}>Interest · optional</span>
        <span className={cn(LABEL, "inline-flex items-center gap-1 text-muted-foreground")} data-star-rating-words role="status">
          {feedback.phase === "saving" ? <Loader2Icon aria-hidden="true" className="size-3 animate-spin" /> : null}
          {feedback.phase === "error" ? "Not saved" : starsWords(value)}
        </span>
      </div>
      <div aria-label="Star rating" className="grid grid-cols-5 gap-x-1.5" role="group">
        {Array.from({ length: STAR_COUNT }, (_, index) => {
          const star = index + 1;
          const filled = value !== null && star <= value;
          return (
            <button
              aria-label={value === star ? `${star} stars. Tap to clear` : `${star} ${star === 1 ? "star" : "stars"}`}
              aria-pressed={value === star}
              className={cn(
                "inline-flex min-w-0 items-center justify-center rounded-[var(--feed-radius-md,16px)] outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring",
                cell,
                filled ? "bg-[var(--feed-control)] text-foreground" : "bg-[var(--feed-control)]/45 text-muted-foreground hover:bg-[var(--feed-control)]/70",
                disabled && "opacity-[var(--feed-quiet,0.6)]",
              )}
              data-filled={filled || undefined}
              data-star={star}
              key={star}
              onClick={() => { if (!disabled) onChange(star); }}
              type="button"
            >
              {/* A solid star against an outline: the difference is the shape, not the colour. */}
              <StarIcon aria-hidden="true" className="size-5" fill={filled ? "currentColor" : "none"} strokeWidth={filled ? 1.5 : 2} />
            </button>
          );
        })}
      </div>
      {feedback.phase === "error" ? <p className="text-xs text-destructive" role="alert">{feedback.message}</p> : null}
    </div>
  );
}

/** A rating shown small and read-only, for a list row: a solid star and the number, so it reads by shape and by digit, never by colour. */
export function StarsMark({ stars }: { stars: number | null }) {
  if (!stars) return null;
  return (
    <span aria-label={starsWords(stars)} className="inline-flex items-center gap-0.5 text-xs font-semibold text-foreground" data-stars-mark={stars} role="img">
      <StarIcon aria-hidden="true" className="size-3.5" fill="currentColor" strokeWidth={1.5} />
      {stars}
    </span>
  );
}
