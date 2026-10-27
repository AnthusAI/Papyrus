"use client";

import {
  ArchiveIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CircleCheckIcon,
  CircleXIcon,
  ExternalLinkIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { REFERENCE_REJECTION_REASON_CODES, type ReferenceRejectionReasonCode } from "../lib/reference-policy";

export type ReviewChoice = "accept" | "reject";

/** The Cyclotron's answer in the card's own vocabulary: Accept or Reject. */
export type CardPrediction =
  | { state: "ready"; choice: ReviewChoice; confidence: number | null }
  | { state: "none" }
  | { state: "loading" }
  | { state: "error" };

export type ReviewCardDecision = {
  note: string;
  reasonCode: ReferenceRejectionReasonCode | null;
};

const REASON_LABELS: Record<ReferenceRejectionReasonCode, string> = {
  out_of_scope: "Out of scope",
  policy_exclusion: "Policy exclusion",
  duplicate: "Duplicate",
  low_quality: "Low quality",
  unavailable: "Unavailable",
  provenance: "Provenance",
  other: "Other",
};

const CHOICE_LABEL: Record<ReviewChoice, string> = { accept: "Accept", reject: "Reject" };

function percent(confidence: number | null): string | null {
  return confidence === null ? null : `${Math.round(confidence * 100)}%`;
}

/**
 * One reusable card for answering a single question: Accept or Reject. The Cyclotron's row is
 * read-only; the human row is the real control and its answer is final. Saves on tap.
 * Written so that story review can reuse it later: it knows nothing about references.
 */
export function ReviewCard({
  children,
  decided,
  disabledReason,
  initialNote = "",
  initialReason = null,
  itemId,
  onArchive,
  onDecide,
  prediction,
  summary,
  title,
  titleHref,
}: {
  children?: ReactNode;
  /** The saved human answer, or null while the item is undecided. */
  decided: ReviewChoice | null;
  /** When set, the controls explain in words why they cannot change anything. */
  disabledReason?: string | null;
  initialNote?: string;
  initialReason?: ReferenceRejectionReasonCode | null;
  itemId: string;
  onArchive?: () => Promise<void> | void;
  onDecide: (choice: ReviewChoice, decision: ReviewCardDecision) => Promise<void> | void;
  prediction: CardPrediction;
  summary?: string | null;
  title: string;
  titleHref?: string | null;
}) {
  const [draft, setDraft] = useState<ReviewChoice | null>(null);
  const [note, setNote] = useState(initialNote);
  const [reason, setReason] = useState<ReferenceRejectionReasonCode | null>(initialReason);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const noteTouched = useRef(false);
  const reasonTouched = useRef(false);
  const savedNote = useRef(initialNote);

  // Saved values from outside (another editor, a reload) refresh whatever the human has not touched.
  useEffect(() => {
    savedNote.current = initialNote;
    if (!noteTouched.current) setNote(initialNote);
  }, [initialNote]);
  useEffect(() => {
    if (!reasonTouched.current) setReason(initialReason);
  }, [initialReason]);

  const chosen = draft ?? decided;

  async function save(choice: ReviewChoice, nextReason: ReferenceRejectionReasonCode | null, nextNote: string) {
    if (disabledReason || inFlight.current) return;
    if (choice === "reject" && !nextReason) return;
    inFlight.current = true;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await onDecide(choice, { note: nextNote.trim(), reasonCode: choice === "reject" ? nextReason : null });
      savedNote.current = nextNote.trim();
      noteTouched.current = false;
      reasonTouched.current = false;
      setDraft(null);
      setSaved(true);
    } catch (failure) {
      setDraft(null);
      setError(failure instanceof Error ? failure.message : "Your answer could not be saved. Tap it again to retry.");
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  function choose(choice: ReviewChoice) {
    if (disabledReason) return;
    if (chosen === choice && draft === null) return; // the selected answer never unselects itself
    setError(null);
    setDraft(choice);
    void save(choice, reason, note);
  }

  function chooseReason(code: ReferenceRejectionReasonCode) {
    if (disabledReason) return;
    setReason(code);
    reasonTouched.current = true;
    if (chosen === "reject") void save("reject", code, note);
  }

  function commitNote() {
    if (!decided || disabledReason || note.trim() === savedNote.current.trim()) return;
    void save(decided, reason, note);
  }

  // Desktop shortcuts: A accepts, R rejects. Never while typing.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "a" || event.key === "A") choose("accept");
      if (event.key === "r" || event.key === "R") choose("reject");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const predictedMarker = (choice: ReviewChoice) => {
    if (prediction.state !== "ready" || prediction.choice !== choice) return null;
    return prediction.choice;
  };
  const matched = decided && prediction.state === "ready" ? prediction.choice === decided : null;

  return (
    <section aria-label="Review" className="space-y-4" data-review-card={itemId}>
      <header className="space-y-1">
        <h2 className="text-lg font-semibold leading-snug text-foreground">{title}</h2>
        {titleHref ? (
          <a className="inline-flex max-w-full items-center gap-1 truncate text-sm text-primary underline-offset-4 hover:underline" href={titleHref} rel="noreferrer" target="_blank">
            <span className="truncate">{titleHref}</span>
            <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
          </a>
        ) : null}
        {summary ? <p className="text-sm text-muted-foreground">{summary}</p> : null}
      </header>

      <div className="space-y-2" data-review-row="cyclotron">
        <div className="flex items-center gap-3">
          <span className="w-20 shrink-0 text-sm font-semibold">Cyclotron</span>
          {prediction.state === "ready" ? (
            <div className="flex flex-1 gap-2">
              {(["accept", "reject"] as const).map((choice) => {
                const predicted = predictedMarker(choice) !== null;
                const verdict = predicted && matched !== null ? (matched ? "match" : "miss") : null;
                return (
                  <span
                    className={cn(
                      "inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-md border px-3 text-sm",
                      predicted ? "border-foreground bg-muted font-semibold" : "border-dashed text-muted-foreground",
                      verdict === "match" && "border-green-700 bg-green-100 text-green-950",
                      verdict === "miss" && "border-red-700 bg-red-100 text-red-950",
                    )}
                    data-cyclotron-choice={choice}
                    data-predicted={predicted || undefined}
                    data-verdict={verdict ?? undefined}
                    key={choice}
                  >
                    {verdict === "match" ? <CircleCheckIcon aria-hidden="true" className="size-4" /> : null}
                    {verdict === "miss" ? <CircleXIcon aria-hidden="true" className="size-4" /> : null}
                    {CHOICE_LABEL[choice]}
                    {predicted && percent(prediction.confidence) ? <small className="text-xs font-normal">{percent(prediction.confidence)}</small> : null}
                    {verdict ? <span className="sr-only">{verdict === "match" ? ", matches your answer" : ", differs from your answer"}</span> : null}
                  </span>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground" data-cyclotron-state={prediction.state}>
              {prediction.state === "loading" ? "Loading…" : prediction.state === "error" ? "Prediction unavailable" : "No prediction"}
            </p>
          )}
        </div>
      </div>

      <div className="space-y-2" data-review-row="you">
        <div className="flex items-center gap-3">
          <span className="w-20 shrink-0 text-sm font-semibold">You</span>
          <div className="flex flex-1 gap-2">
            {(["accept", "reject"] as const).map((choice) => {
              const on = chosen === choice;
              return (
                <Button
                  aria-disabled={disabledReason ? true : undefined}
                  aria-pressed={on}
                  className="min-h-14 flex-1 text-base"
                  data-review-choice={choice}
                  key={choice}
                  onClick={() => choose(choice)}
                  type="button"
                  variant={on ? (choice === "accept" ? "default" : "destructive") : "outline"}
                >
                  {on ? <CheckIcon aria-hidden="true" className="size-5" /> : null}
                  {CHOICE_LABEL[choice]}
                </Button>
              );
            })}
          </div>
        </div>
        <div className="min-h-5 pl-[5.75rem] text-sm" role="status">
          {saving ? "Saving…" : saved ? (
            <span className="inline-flex items-center gap-1" data-review-saved><CheckIcon aria-hidden="true" className="size-4" />Saved</span>
          ) : null}
        </div>
        {disabledReason ? <p className="text-sm text-muted-foreground" data-review-disabled-reason>{disabledReason}</p> : null}
        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
      </div>

      <label className="block text-sm font-medium">
        Why? (optional)
        <textarea
          aria-label="Why? (optional)"
          className="mt-1 block min-h-24 w-full rounded-md border bg-background p-3 text-base font-normal"
          onBlur={commitNote}
          onChange={(event) => { setNote(event.target.value); noteTouched.current = true; setSaved(false); }}
          placeholder="Say what made this an easy yes or a clear no. Your note teaches the Cyclotron."
          value={note}
        />
      </label>

      {chosen === "reject" ? (
        <div className="space-y-2" data-review-reasons>
          <p className="text-sm font-medium">Reason for rejecting</p>
          <div className="flex flex-wrap gap-2">
            {REFERENCE_REJECTION_REASON_CODES.map((code) => (
              <Button
                aria-disabled={disabledReason ? true : undefined}
                aria-pressed={reason === code}
                className="min-h-10"
                data-review-reason={code}
                key={code}
                onClick={() => chooseReason(code)}
                type="button"
                variant={reason === code ? "default" : "outline"}
              >
                {reason === code ? <CheckIcon aria-hidden="true" className="size-4" /> : null}
                {REASON_LABELS[code]}
              </Button>
            ))}
          </div>
          {!reason ? <p className="text-sm text-muted-foreground">Choose a reason to save your Reject.</p> : null}
        </div>
      ) : null}

      {children}

      {onArchive ? (
        <Button aria-label="Archive reference" onClick={() => { if (!disabledReason) void onArchive(); }} size="sm" type="button" variant="ghost">
          <ArchiveIcon aria-hidden="true" className="size-4" />
          Archive
        </Button>
      ) : null}
    </section>
  );
}

/** Sticky Previous / position / Next bar for working through a queue. */
export function ReviewQueueBar({
  caughtUp = false,
  onNext,
  onPrevious,
  position,
  total,
}: {
  caughtUp?: boolean;
  onNext: () => void;
  onPrevious: () => void;
  /** 1-based position, or null when the open item is not in the queue. */
  position: number | null;
  total: number;
}) {
  const atStart = position === 1;
  return (
    <nav
      aria-label="Review queue"
      className="sticky bottom-0 z-10 flex shrink-0 items-center gap-2 border-t border-border bg-card px-3 py-2"
      data-review-queue-bar
    >
      <Button
        aria-disabled={atStart || undefined}
        aria-label="Previous"
        className={cn("min-h-12 flex-1 text-base", atStart && "opacity-60")}
        onClick={() => { if (!atStart) onPrevious(); }}
        type="button"
        variant="outline"
      >
        <ChevronLeftIcon aria-hidden="true" className="size-5" />
        Previous
      </Button>
      <span className="min-w-20 text-center text-sm" data-review-queue-position>
        {caughtUp ? "All caught up" : position ? `${position} of ${total}` : `${total} in list`}
      </span>
      <Button
        aria-disabled={caughtUp || undefined}
        aria-label="Next"
        className={cn("min-h-12 flex-1 text-base", caughtUp && "opacity-60")}
        onClick={() => { if (!caughtUp) onNext(); }}
        type="button"
        variant="outline"
      >
        Next
        <ChevronRightIcon aria-hidden="true" className="size-5" />
      </Button>
    </nav>
  );
}

/** Swipe left for Next, right for Previous; ← and → on a keyboard. Never required. */
export function useQueueGestures({ onNext, onPrevious }: { onNext: () => void; onPrevious: () => void }) {
  const start = useRef<{ x: number; y: number } | null>(null);
  const handlers = useRef({ onNext, onPrevious });
  handlers.current = { onNext, onPrevious };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (event.key === "ArrowRight") handlers.current.onNext();
      if (event.key === "ArrowLeft") handlers.current.onPrevious();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return {
    onPointerDown(event: ReactPointerEvent) {
      if (event.pointerType !== "touch") return;
      start.current = { x: event.clientX, y: event.clientY };
    },
    onPointerUp(event: ReactPointerEvent) {
      const origin = start.current;
      start.current = null;
      if (!origin || event.pointerType !== "touch") return;
      const dx = event.clientX - origin.x;
      const dy = event.clientY - origin.y;
      if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 2) return;
      if (dx < 0) handlers.current.onNext();
      else handlers.current.onPrevious();
    },
    style: { touchAction: "pan-y" } as const,
  };
}
