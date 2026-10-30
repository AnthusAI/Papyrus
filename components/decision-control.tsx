"use client";

import { useEffect, useId, useState } from "react";
import { CheckIcon, Loader2Icon, XIcon } from "lucide-react";
import { UNRECORDED_CONFIDENCE } from "../lib/reference-feed-ranking";
import { cn } from "@/lib/utils";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";
import type { CardPrediction, ReviewChoice } from "./reference-review-card";

/**
 * One classification, in two stages: a model predicts it, a person decides it.
 *
 *   PREDICTED ACCEPT
 *   [=========== 96% ==========|                ]   the prediction's own confidence, in its own bar
 *   [ ✓ Accept  PREDICTED ]  [ ✕ Reject ]            one pair of segments; the predicted one is pre-filled, in its own tone
 *   REASON · OPTIONAL
 *   [ Why? In your own words… ]                      written, always in view, full width
 *   ✓ Recorded · confirms the prediction             one status line for the whole block
 *
 * The prediction and the answer share one row of segments rather than a row each: they are not two
 * voters, they are one decision before and after a person touched it. Once decided, a small marker
 * stays on the segment the model picked — on the losing one if it was overturned — so the comparison
 * survives the answer without a second row. The bar belongs to the model, so it never moves when the
 * person answers; only its tone changes.
 *
 * The verdict never tints the person's own choice: a decided segment is always `--primary`, and
 * `--feed-verdict-*` colours the marker and the bar. An overturned Reject painted red reads as "your
 * answer is wrong" rather than "the model's was".
 *
 * No engine or product name appears in the copy: the component knows about predictions, not about
 * what made them (AGENTS.md: a deployment publishes about any subject with any classifier behind it).
 *
 * Every tone, corner and opacity is a feed token from newsroom-organizer.css; the values after the
 * comma are the last resort for a surface that declares none.
 */

export type RatingFeedback = { phase: "idle" | "saving" | "saved" | "error"; message?: string };

/** P(accept) from a prediction: its confidence is in the side it chose; an unrecorded confidence is a mild lean. */
export function predictionAcceptProbability(prediction: Extract<CardPrediction, { state: "ready" }>): number {
  const confidence = prediction.confidence ?? UNRECORDED_CONFIDENCE;
  return prediction.choice === "accept" ? confidence : 1 - confidence;
}

/** How far, in percent of the whole bar, the fill reaches from the centre: |P(accept) - 0.5| * 2, over the two halves. */
export function confidenceFillPercent(probability: number): number {
  return Math.min(100, Math.abs(probability - 0.5) * 100 * 2);
}

const WORD: Record<ReviewChoice, string> = { accept: "Accept", reject: "Reject" };
const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";
/** A fill shorter than this cannot hold its own percentage, so the number sits beside it. */
const NARROW_FILL = 14;

export function DecisionControl({
  answer,
  decided = null,
  disabled = false,
  disabledReason = null,
  feedback = { phase: "idle" },
  needsReason = false,
  note = null,
  onChoose,
  onReasonChange,
  onReasonCommit,
  prediction,
  reason = "",
  reasonRequiredFor = null,
  showPrediction = true,
  showReason = true,
  size = "compact",
  statusOverlay = false,
  surface = "footer",
}: {
  /** The side shown as chosen. It may be an answer that is still saving. */
  answer: ReviewChoice | null;
  /** The saved answer, which the Confirmed / Overturned verdict compares against. */
  decided?: ReviewChoice | null;
  disabled?: boolean;
  disabledReason?: string | null;
  feedback?: RatingFeedback;
  /** The answer is staged and waiting for a written reason before it can be recorded. */
  needsReason?: boolean;
  /** A short line shown in the status row beside the saved tick. It never adds a row. */
  note?: string | null;
  onChoose: (choice: ReviewChoice) => void;
  onReasonChange?: (text: string) => void;
  /** Save the reason on its own (on blur, or from the status row). */
  onReasonCommit?: () => void;
  prediction: CardPrediction;
  /** The written reason, owned by the caller. */
  reason?: string;
  /** The side that cannot be recorded without a written reason. */
  reasonRequiredFor?: ReviewChoice | null;
  /** False for an item with nothing to predict: the bar and the caption are left out. */
  showPrediction?: boolean;
  /** False where the surrounding card owns the reason field. */
  showReason?: boolean;
  size?: "compact" | "large";
  /** Lay the status line over the bottom padding of the nearest positioned ancestor, so it adds no height. */
  statusOverlay?: boolean;
  /** The tone the control sits on, so the bar's centre notch matches it. */
  surface?: "footer" | "card";
}) {
  const fieldId = useId();
  const ready = prediction.state === "ready" ? prediction : null;
  const verdict = ready && decided ? (ready.choice === decided ? "match" : "miss") : null;
  const saving = feedback.phase === "saving";
  const [reasonDirty, setReasonDirty] = useState(false);
  useEffect(() => { if (feedback.phase === "saved") setReasonDirty(false); }, [feedback.phase]);

  const probability = ready ? predictionAcceptProbability(ready) : 0.5;
  const half = confidenceFillPercent(probability) / 2; // percent of the full bar, one side of the centre
  const leansAccept = probability >= 0.5;
  const confidenceText = ready ? (ready.confidence !== null ? `${Math.round(ready.confidence * 100)}%` : "unrecorded") : null;
  const narrow = half < NARROW_FILL;
  const cell = size === "large" ? "min-h-14 text-base" : "min-h-12 text-sm";
  const field = size === "large" ? "min-h-16" : "min-h-9";

  const caption = ready
    ? `Predicted ${WORD[ready.choice]}`
    : prediction.state === "loading" ? "Reading the prediction…"
      : prediction.state === "error" ? "Prediction unavailable" : "No prediction";

  /* What the chosen segment says about itself while the answer is in flight or held back. A segment
     never claims to be unrecorded while it is being recorded. */
  const stagedWord = saving ? (decided ? "Updating…" : "Sending…") : needsReason ? "Needs a reason" : null;

  return (
    <div className="@container/decision grid gap-y-2" data-decision-control data-rating-grid>
      {showPrediction ? (
        <div className="grid gap-y-0.5" data-prediction>
          <span className={cn(LABEL, "text-muted-foreground")} data-prediction-caption>{caption}</span>
          <div
            aria-label={ready ? `Prediction: ${WORD[ready.choice]}, ${confidenceText} confident` : caption}
            className="relative h-4 w-full overflow-hidden rounded-full bg-[var(--feed-control)]"
            data-confidence-bar
            data-confidence-direction={ready ? (leansAccept ? "accept" : "reject") : "none"}
            data-prediction-state={ready ? undefined : prediction.state}
            role="img"
          >
            {ready ? (
              <span
                className={cn(
                  "absolute inset-y-0 flex items-center rounded-full",
                  leansAccept ? "justify-end" : "justify-start",
                  verdict === "match" ? "bg-[var(--feed-verdict-match-fill,#059669)]"
                    : verdict === "miss" ? "bg-[var(--feed-verdict-miss-fill,#dc2626)]"
                      : "bg-[var(--foreground-muted)]",
                )}
                data-confidence-fill
                data-fill-percent={Math.round(half * 2)}
                style={{ left: leansAccept ? `${50 - half}%` : "50%", width: `${half}%` }}
              >
                {/* The confidence is printed in the bar and nowhere else, so no button has to carry a number. */}
                {narrow ? null : <small className={cn(LABEL, "px-1.5 text-[var(--feed-card)] whitespace-nowrap")} data-confidence-value>{confidenceText}</small>}
              </span>
            ) : null}
            {ready && narrow ? (
              <small
                className={cn(LABEL, "absolute top-0.5 text-muted-foreground whitespace-nowrap")}
                data-confidence-value
                style={leansAccept ? { left: `${50 - half}%`, transform: "translateX(-100%)" } : { left: `${50 + half}%` }}
              >
                {confidenceText}
              </small>
            ) : null}
            <span aria-hidden="true" className={cn("absolute inset-y-0 left-1/2 w-1 -translate-x-1/2", surface === "footer" ? "bg-[var(--feed-footer)]" : "bg-[var(--feed-card)]")} />
          </div>
        </div>
      ) : null}

      <div aria-label="Classification" className="grid grid-cols-2 gap-x-1.5" data-review-row="you" role="group">
        {(["accept", "reject"] as const).map((choice) => {
          const on = answer === choice;
          const predicted = ready?.choice === choice;
          const proposed = predicted && !answer;
          const Icon = choice === "accept" ? CheckIcon : XIcon;
          const sub = proposed ? "Predicted"
            : on ? (stagedWord ?? (verdict === "miss" ? "Overturned" : verdict === "match" ? "Confirmed" : decided === choice ? "Recorded" : null))
              : null;
          return (
            <button
              aria-disabled={disabled ? true : undefined}
              aria-pressed={on}
              className={cn(
                "relative inline-flex min-w-0 flex-col items-center justify-center gap-px rounded-[var(--feed-radius-md,16px)] px-2 font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring @max-[17rem]/decision:px-1",
                cell,
                // Three degrees of finish, in tone alone: the feed register has no borders to spend
                // (newsroom-organizer.css strips them), so a chosen answer is the solid fill, the
                // predicted side is the control tone, and an untouched side is quieter still.
                on ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]"
                  : proposed ? "bg-[var(--feed-control)] text-foreground hover:bg-[var(--feed-control)]/70"
                    : "bg-[var(--feed-control)]/45 text-muted-foreground hover:bg-[var(--feed-control)]/70",
                disabled && !on && "opacity-[var(--feed-quiet,0.6)]",
              )}
              data-predicted={predicted || undefined}
              data-review-choice={choice}
              data-state={on ? (saving || needsReason ? "staged" : "decided") : proposed ? "predicted" : "idle"}
              key={choice}
              onClick={() => { if (!disabled) onChoose(choice); }}
              type="button"
            >
              {/* The model's opinion survives the answer, on the segment it picked. */}
              {predicted && answer ? (
                <span
                  className={cn(
                    "absolute top-1.5 right-2 opacity-55",
                    verdict === "match" && "text-[var(--feed-verdict-match-fill,#059669)] opacity-100",
                    verdict === "miss" && "text-[var(--feed-verdict-miss-fill,#dc2626)] opacity-100",
                  )}
                  data-prediction-mark
                  data-verdict={verdict ?? undefined}
                  title="this is what was predicted"
                >
                  <svg aria-hidden="true" className="size-3" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="8" />
                    <circle cx="12" cy="12" fill="currentColor" r="2.6" stroke="none" />
                  </svg>
                </span>
              ) : null}
              <span className="flex items-center gap-1.5">
                <Icon aria-hidden="true" className={cn("size-4", !on && "opacity-[var(--feed-quiet,0.6)]")} />
                {WORD[choice]}
              </span>
              {sub ? <span className={cn(LABEL, "opacity-75")} data-choice-state>{sub}</span> : null}
              {verdict && predicted ? <span className="sr-only">{verdict === "match" ? ", this is what was predicted" : ", the prediction was the other way"}</span> : null}
            </button>
          );
        })}
      </div>

      {showReason ? (
        <div className="grid gap-y-1.5" data-review-reason>
          <label className={cn(LABEL, "text-muted-foreground")} htmlFor={fieldId}>
            Reason{reasonRequiredFor ? ` · required to ${WORD[reasonRequiredFor].toLowerCase()}` : " · optional"}
          </label>
          {/* Written reasons only. A row of canned answers collects a label the model mostly has already;
              what trains the next prediction is a sentence. */}
          <AutoGrowTextarea
            className={cn(
              "w-full rounded-[var(--feed-radius-md,16px)] border-0 bg-[var(--feed-control)] px-3 py-2 text-sm leading-5 text-foreground outline-none transition-[min-height] placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring",
              field,
            )}
            disabled={disabled}
            id={fieldId}
            onBlur={() => { if (!disabled) onReasonCommit?.(); }}
            onChange={(event) => { setReasonDirty(true); onReasonChange?.(event.target.value); }}
            placeholder="Why? In your own words…"
            value={reason}
          />
        </div>
      ) : null}

      <div
        className={cn(
          "flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground",
          // The overlay strip is 16px tall: a question with a button, or an error, needs a row of its own.
          statusOverlay && !needsReason && feedback.phase !== "error" ? "absolute inset-x-4 bottom-0 h-4 overflow-hidden leading-4" : "min-h-5",
        )}
        data-feed-saved
        role="status"
      >
        {note ? <span data-feed-reason>{note}</span> : null}
        {needsReason ? (
          <>
            <span className="font-semibold text-foreground">A reason is needed to record {WORD[answer ?? "reject"]}</span>
            <button
              className="rounded-[var(--feed-radius-md,16px)] bg-[var(--primary)] px-2.5 py-0.5 font-semibold text-[var(--primary-foreground)] outline-none focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]"
              disabled={!reason.trim()}
              data-review-record
              onClick={() => { if (answer) onChoose(answer); }}
              type="button"
            >
              Record
            </button>
          </>
        ) : null}
        {saving ? <span className="inline-flex items-center gap-1"><Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Recording…</span> : null}
        {feedback.phase === "saved" && !needsReason ? (
          <span className="inline-flex items-center gap-1 text-foreground" data-review-saved>
            <CheckIcon aria-hidden="true" className="size-3.5" />
            Recorded
            {verdict ? <span className="text-muted-foreground">· {verdict === "match" ? "confirms" : "overturns"} the prediction</span> : null}
            {showReason ? (
              reasonDirty ? <span className="text-muted-foreground">· reason not saved yet</span>
                : reason.trim() ? <span className="text-muted-foreground">· reason saved</span>
                  : <span className="text-muted-foreground">· no reason given</span>
            ) : null}
          </span>
        ) : null}
        {feedback.phase === "saved" && reasonDirty && showReason ? (
          <button
            className="rounded-[var(--feed-radius-md,16px)] bg-[var(--primary)] px-2.5 py-0.5 font-semibold text-[var(--primary-foreground)] outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
            data-review-save-reason
            onClick={() => onReasonCommit?.()}
            type="button"
          >
            Save reason
          </button>
        ) : null}
      </div>
      {disabledReason ? <p className="text-xs text-muted-foreground" data-review-disabled-reason>{disabledReason}</p> : null}
      {feedback.phase === "error" ? <p className="text-xs text-destructive" role="alert">{feedback.message}</p> : null}
    </div>
  );
}
