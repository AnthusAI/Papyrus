"use client";

import { CheckIcon, CircleCheckIcon, CircleXIcon, Loader2Icon, XIcon } from "lucide-react";
import { UNRECORDED_CONFIDENCE } from "../lib/reference-feed-ranking";
import { cn } from "@/lib/utils";
import type { CardPrediction, ReviewChoice } from "./reference-review-card";

/**
 * The rating area of a card: one grid, three columns (label | Accept | Reject), and the two rows share its columns exactly.
 *   Cyclotron   [ Accept 96% ]  [ Reject ]      read only; the predicted side is highlighted with its confidence
 *               [====== confidence bar, centred at 50% ======]
 *   You         [ Accept ]      [ Reject ]      the real buttons, each directly under its matching cell
 * Feedback is never colour alone: before you answer the predicted cell is neutral-accent with a check or cross; after, it turns
 * green with a CircleCheck (Match) or red with a CircleX (Miss), and the confidence bar tints the same way. Your chosen button is
 * filled. Flat tones and rounded shapes only, no borders.
 */

export type RatingFeedback = { phase: "idle" | "saving" | "saved" | "error"; message?: string };

/** P(accept) from a prediction: its confidence is in the side it chose; an unrecorded confidence is a mild lean. */
export function predictionAcceptProbability(prediction: Extract<CardPrediction, { state: "ready" }>): number {
  const confidence = prediction.confidence ?? UNRECORDED_CONFIDENCE;
  return prediction.choice === "accept" ? confidence : 1 - confidence;
}

/** How far, in percent of the whole bar, the fill reaches from the centre: |P(accept) - 0.5| * 2, over the two halves. */
export function confidenceFillPercent(probability: number): number {
  return Math.min(100, Math.abs(probability - 0.5) * 2 * 100);
}

const WORD: Record<ReviewChoice, string> = { accept: "Accept", reject: "Reject" };

const TONE = {
  match: "bg-emerald-600/20 text-emerald-900 dark:bg-emerald-400/20 dark:text-emerald-100",
  miss: "bg-red-600/20 text-red-900 dark:bg-red-400/20 dark:text-red-100",
} as const;
const FILL = { match: "bg-emerald-600 dark:bg-emerald-400", miss: "bg-red-600 dark:bg-red-400", neutral: "bg-[var(--primary)]" } as const;

export function RatingGrid({
  answer,
  decided = answer,
  disabled = false,
  disabledReason = null,
  feedback = { phase: "idle" },
  note = null,
  onChoose,
  prediction,
  showPrediction = true,
  size = "compact",
  statusOverlay = false,
  surface = "footer",
}: {
  /** The side the buttons show as chosen (it may be a pending choice that is still saving). */
  answer: ReviewChoice | null;
  /** The saved human answer, which the Match / Miss verdict compares against. */
  decided?: ReviewChoice | null;
  disabled?: boolean;
  disabledReason?: string | null;
  feedback?: RatingFeedback;
  /** A short line shown in the status row beside the Saved tick (for example the reason). It never adds a row. */
  note?: string | null;
  onChoose: (choice: ReviewChoice) => void;
  prediction: CardPrediction;
  /** False for a card with nothing to predict (an AI draft): the Cyclotron row and the "You" label are left out and only the two buttons remain. */
  showPrediction?: boolean;
  size?: "compact" | "large";
  /** Lay the Saved / note line over the bottom padding of the nearest positioned ancestor, so it adds no height under the buttons. */
  statusOverlay?: boolean;
  /** The tone the grid sits on, so the bar's centre notch matches it. */
  surface?: "footer" | "card";
}) {
  const ready = prediction.state === "ready" ? prediction : null;
  const verdict = ready && decided ? (ready.choice === decided ? "match" : "miss") : null;
  const probability = ready ? predictionAcceptProbability(ready) : 0.5;
  const half = confidenceFillPercent(probability) / 2; // percent of the full bar width, on one side of the centre
  const leansAccept = probability >= 0.5;
  const confidenceText = ready && ready.confidence !== null ? `${Math.round(ready.confidence * 100)}%` : null;
  const cell = size === "large" ? "min-h-14 text-base" : "min-h-12 text-sm";
  const label = size === "large" ? "text-sm" : "text-xs";

  return (
    <div
      className={cn(
        "grid gap-x-2 gap-y-2",
        showPrediction ? "grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1fr)]" : "grid-cols-2",
        showPrediction && size === "large" && "grid-cols-[5rem_minmax(0,1fr)_minmax(0,1fr)]",
      )}
      data-rating-grid
    >
      {showPrediction ? <div className="col-span-3 grid grid-cols-subgrid items-stretch gap-y-2" data-review-row="cyclotron">
        <span className={cn("self-center font-semibold", label)}>Cyclotron</span>
        {(["accept", "reject"] as const).map((choice) => {
          const predicted = ready?.choice === choice;
          const Icon = predicted ? (verdict === "match" ? CircleCheckIcon : verdict === "miss" ? CircleXIcon : choice === "accept" ? CheckIcon : XIcon) : null;
          return (
            <span
              className={cn(
                "flex flex-col items-center justify-center rounded-[16px] px-2 py-1.5 text-center",
                cell,
                !predicted && "bg-[var(--feed-control)]/45 text-muted-foreground",
                predicted && !verdict && "bg-[var(--feed-control)] font-semibold text-[var(--primary)]",
                predicted && verdict && cn("font-semibold", TONE[verdict]),
              )}
              data-cyclotron-choice={choice}
              data-predicted={predicted || undefined}
              data-verdict={predicted && verdict ? verdict : undefined}
              key={choice}
            >
              <span className="inline-flex items-center gap-1.5">
                {Icon ? <Icon aria-hidden="true" className="size-4 shrink-0" /> : null}
                {WORD[choice]}
                {predicted && confidenceText ? <small className="text-xs font-normal opacity-80">{confidenceText}</small> : null}
              </span>
              {predicted && verdict ? <small className="text-xs font-medium" data-verdict-word>{verdict === "match" ? "Match" : "Miss"}</small> : null}
              {predicted && verdict ? <span className="sr-only">{verdict === "match" ? ", matches your answer" : ", differs from your answer"}</span> : null}
            </span>
          );
        })}
        <div className="col-span-2 col-start-2 flex flex-col justify-center" data-confidence>
          <div
            aria-label={ready ? `Cyclotron confidence: leans ${leansAccept ? "Accept" : "Reject"}, ${Math.round(confidenceFillPercent(probability))} percent of the way` : "No confidence"}
            className="relative h-2.5 w-full overflow-hidden rounded-full bg-[var(--feed-control)]"
            data-confidence-bar
            data-confidence-direction={ready ? (leansAccept ? "accept" : "reject") : "none"}
            role="img"
          >
            {ready ? (
              <span
                className={cn("absolute inset-y-0 rounded-full", FILL[verdict ?? "neutral"])}
                data-confidence-fill
                data-fill-percent={Math.round(half * 2)}
                style={{ left: leansAccept ? `${50 - half}%` : "50%", width: `${half}%` }}
              />
            ) : null}
            <span aria-hidden="true" className={cn("absolute inset-y-0 left-1/2 w-1 -translate-x-1/2", surface === "footer" ? "bg-[var(--feed-footer)]" : "bg-[var(--feed-card)]")} />
          </div>
          {/* Screen-reader status only: a visible line under the bar would push it off the middle between the Cyclotron and You rows. */}
          <small className="sr-only" data-cyclotron-state={prediction.state === "ready" ? undefined : prediction.state}>
            {prediction.state === "ready" ? "" : prediction.state === "loading" ? "Loading…" : prediction.state === "error" ? "Prediction unavailable" : "No prediction"}
          </small>
        </div>
      </div> : null}

      <div className={cn("grid grid-cols-subgrid items-stretch", showPrediction ? "col-span-3" : "col-span-2")} data-review-row="you">
        {showPrediction ? <span className={cn("self-center font-semibold", label)}>You</span> : null}
        {(["accept", "reject"] as const).map((choice) => {
          const on = answer === choice;
          const Icon = choice === "accept" ? CheckIcon : XIcon;
          return (
            <button
              aria-disabled={disabled ? true : undefined}
              aria-pressed={on}
              className={cn(
                "inline-flex items-center justify-center gap-1.5 rounded-[16px] px-2 font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                cell,
                on ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "bg-[var(--feed-control)] text-foreground hover:bg-[var(--feed-control)]/70",
                disabled && !on && "opacity-60",
              )}
              data-review-choice={choice}
              key={choice}
              onClick={() => onChoose(choice)}
              type="button"
            >
              <Icon aria-hidden="true" className={cn("size-4", !on && "opacity-60")} />
              {WORD[choice]}
            </button>
          );
        })}
      </div>

      <div className={cn("flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground", statusOverlay ? "absolute inset-x-4 bottom-0 h-4 overflow-hidden leading-4" : cn("min-h-5", showPrediction ? "col-span-3" : "col-span-2"))} data-feed-saved role="status">
        {note ? <span data-feed-reason>{note}</span> : null}
        {feedback.phase === "saving" ? <span className="inline-flex items-center gap-1"><Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Saving…</span> : null}
        {feedback.phase === "saved" ? <span className="inline-flex items-center gap-1" data-review-saved><CheckIcon aria-hidden="true" className="size-3.5" />Saved</span> : null}
      </div>
      {disabledReason ? <p className={cn("text-xs text-muted-foreground", showPrediction ? "col-span-3" : "col-span-2")} data-review-disabled-reason>{disabledReason}</p> : null}
      {feedback.phase === "error" ? <p className={cn("text-xs text-destructive", showPrediction ? "col-span-3" : "col-span-2")} role="alert">{feedback.message}</p> : null}
    </div>
  );
}
