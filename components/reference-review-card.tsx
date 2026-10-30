"use client";

import {
  ArchiveIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DecisionControl } from "./decision-control";
import { useRatingStore, type RatingController } from "./use-reference-ratings";
import type { ReferenceRejectionReasonCode } from "../lib/reference-policy";

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

export function predictionFromDecision(decision: { label: string; positiveLabel: string | null; confidence: number | null }): CardPrediction {
  return { state: "ready", choice: decision.label === (decision.positiveLabel ?? "include") ? "accept" : "reject", confidence: decision.confidence };
}

/**
 * One reusable card for answering a single question: Accept or Reject. The Cyclotron's row is
 * read-only; the human row is the real control and its answer is final. Saves on tap.
 * Written so that story review can reuse it later: it knows nothing about references.
 */
export function ReviewCard({
  children,
  decided,
  dek,
  disabledReason,
  initialNote = "",
  initialReason = null,
  itemId,
  meta,
  onArchive,
  sourcePreview,
  onDecide,
  prediction,
  summary,
  title,
  titleHref,
  ratings,
}: {
  children?: ReactNode;
  /** A shared rating store, so the grid card and this card stay in step. Optional: the card works alone without it. */
  ratings?: RatingController;
  /** The saved human answer, or null while the item is undecided. */
  decided: ReviewChoice | null;
  /** The source's own subtitle or blurb, shown under the title. */
  dek?: string | null;
  /** When set, the controls explain in words why they cannot change anything. */
  disabledReason?: string | null;
  initialNote?: string;
  initialReason?: ReferenceRejectionReasonCode | null;
  itemId: string;
  /** Badges (type, status) shown under the title and link. */
  meta?: ReactNode;
  onArchive?: () => Promise<void> | void;
  onDecide: (choice: ReviewChoice, decision: ReviewCardDecision) => Promise<void> | void;
  prediction: CardPrediction;
  /** The live preview of the source, shown under its link. It renders nothing when there is none. */
  sourcePreview?: ReactNode;
  summary?: string | null;
  title: string;
  titleHref?: string | null;
}) {
  // The rating state lives in a store. Given one (`ratings`), the grid card and this card share it, so a vote or a reason typed in
  // either shows in both at once; without one the card keeps a private store, exactly as before.
  const local = useRatingStore({
    save: (_id, choice, detail) => onDecide(choice, detail),
    saved: () => decided,
    seed: () => ({ note: initialNote, reasonCode: initialReason }),
  });
  const store = ratings ?? local;
  const item = store.get(itemId);
  const note = item.note ?? initialNote;
  const chosen = item.pending ?? decided;
  const choose = (choice: ReviewChoice) => { if (!disabledReason) store.choose(itemId, choice); };
  const commitNote = () => { if (!disabledReason) store.commitNote(itemId); };

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

  return (
    <section aria-label="Review" className="space-y-4" data-review-card={itemId}>
      {/* Title, blurb, link, badges, summary: what the item is, read top to bottom before the rating. */}
      <header className="space-y-2">
        <h2 className="text-lg font-semibold leading-snug text-foreground">{title}</h2>
        {dek && dek.trim() !== title.trim() ? <p className="text-base text-muted-foreground" data-review-dek>{dek}</p> : null}
        {titleHref ? (
          <a className="inline-flex max-w-full items-center gap-1 truncate text-sm text-primary underline-offset-4 hover:underline" href={titleHref} rel="noreferrer" target="_blank">
            <span className="truncate">{titleHref}</span>
            <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
          </a>
        ) : null}
        {sourcePreview}
        {meta}
        {summary ? (
          <div className="space-y-1 pt-1" data-review-summary>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Summary</h3>
            <p className="text-sm leading-relaxed text-foreground">{summary}</p>
          </div>
        ) : null}
      </header>

      <DecisionControl
        answer={chosen}
        decided={decided}
        disabled={Boolean(disabledReason)}
        disabledReason={disabledReason}
        feedback={item.feedback}
        needsReason={item.askReason}
        onChoose={choose}
        onReasonChange={(text) => store.setNote(itemId, text)}
        onReasonCommit={commitNote}
        prediction={prediction}
        reason={note}
        reasonRequiredFor="reject"
        size="large"
        surface="card"
      />

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
  more = false,
  anchored = false,
}: {
  /** On a wide screen, pin the bar to the bottom-right corner of the viewport (the detail column's width), whatever scrolls. A sheet's own bar is not anchored. */
  anchored?: boolean;
  caughtUp?: boolean;
  onNext: () => void;
  onPrevious: () => void;
  /** 1-based position, or null when the open item is not in the queue. */
  position: number | null;
  total: number;
  /** More References can be read beyond the `total` loaded so far: the count says "24+" rather than claiming that is all of them. */
  more?: boolean;
}) {
  const atStart = position === 1;
  const count = more ? `${total}+` : String(total);
  return (
    <nav
      aria-label="Review queue"
      className={cn("sticky bottom-0 z-10 flex shrink-0 items-center gap-2 bg-[var(--feed-card)] px-3 py-2", anchored && "lg:fixed lg:bottom-0 lg:right-0 lg:w-[calc(24rem+1rem)] lg:pr-7 xl:w-[calc(28rem+1rem)]")}
      data-review-queue-anchored={anchored || undefined}
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
        {caughtUp ? "All caught up" : position ? `${position} of ${count}` : `${count} in list`}
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
