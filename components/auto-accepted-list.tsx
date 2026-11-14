"use client";

import { BotIcon, Loader2Icon, RefreshCwIcon, ScaleIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import {
  AUTO_ACCEPTED_EMPTY_TEXT,
  autoAcceptedBy,
  confidenceFromReason,
} from "../lib/auto-accepted-references";
import { referenceLineageId } from "../lib/newsroom-references";
import { scoreFeedItem } from "../lib/reference-feed-ranking";
import type { PredictionStatuses } from "../lib/reference-predictions";
import type { ReferencePreview } from "../lib/reference-preview";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import type { CaptureStatus } from "../lib/reference-capture";
import { cn } from "@/lib/utils";
import { FEED_GRID, FeedCard, ReferenceFeedSkeleton, type ReferenceFeedProps } from "./reference-feed";
import type { RatingController } from "./use-reference-ratings";

const formatAcceptedAt = (value: string | null | undefined): string | null => {
  const at = Date.parse(String(value ?? ""));
  if (!Number.isFinite(at)) return null;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(new Date(at));
};

/** Why one Reference was accepted without an editor: who did it, how sure the Cyclotron was, and the reason it recorded. */
function WhyAccepted({ decision, reference }: { decision: RelevanceDecisionView | undefined; reference: ReferenceRecord }) {
  const lineageId = referenceLineageId(reference);
  const byRule = autoAcceptedBy(reference) === "rule";
  const confidence = byRule ? null : decision?.confidence ?? confidenceFromReason(reference.curationStatusReason);
  const at = formatAcceptedAt(reference.curationStatusUpdatedAt);
  return (
    <div className="space-y-1.5 rounded-2xl bg-[var(--feed-card)] px-4 py-3 text-sm" data-auto-accepted-why={lineageId}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-muted-foreground">
        <BotIcon aria-hidden="true" className="size-3.5" />
        <span data-auto-accepted-by={byRule ? "rule" : "cyclotron"}>{byRule ? "Accepted by a monitor's rule" : "Accepted by the Cyclotron"}</span>
        {confidence !== null ? <span className="inline-flex items-center gap-1 text-foreground" data-auto-accepted-confidence><ScaleIcon aria-hidden="true" className="size-3.5" />{Math.round(confidence * 100)}% sure</span> : null}
        {at ? <span>· {at}</span> : null}
      </p>
      <p className="leading-relaxed text-foreground" data-auto-accepted-reason>
        {reference.curationStatusReason?.trim() || "No reason was recorded for this acceptance."}
      </p>
    </div>
  );
}

function MoreSentinel({ hasMore, loadingMore, onLoadMore, itemCount }: { hasMore: boolean; loadingMore: boolean; onLoadMore: () => void; itemCount: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || !hasMore || loadingMore || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) onLoadMore(); }, {
      root: element.closest("[data-radix-scroll-area-viewport]"),
      rootMargin: "0px 0px 800px 0px",
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasMore, itemCount, loadingMore, onLoadMore]);
  if (!hasMore) return null;
  return (
    <div className="flex min-h-12 items-center justify-center gap-3 text-sm text-muted-foreground" data-auto-accepted-more ref={ref} role="status">
      <Loader2Icon aria-hidden="true" className={cn("size-4", loadingMore && "animate-spin")} />
      {loadingMore ? "Reading more…" : (
        <button className="rounded-full bg-[var(--feed-control)] px-4 py-2 font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={onLoadMore} type="button">Show more</button>
      )}
    </div>
  );
}

/**
 * Everything accepted without an editor, newest first, as the same cards the feed uses: the same Accept and Reject controls, and a Reject
 * asks for its reason in the same box. Under each card, the reason it was accepted and how sure the Cyclotron was.
 * The page hides a card once an editor has voted on its Reference (a Reject or an Accept takes it out of the list). Accept confirms it as the editor's own answer (the reason is optional), so it leaves too.
 */
export function AutoAcceptedList({
  captures,
  decisions,
  disabledReason,
  error,
  hasMore,
  items,
  loading,
  loadingMore,
  messageCounts,
  now,
  onLoadMore,
  onOpen,
  onRate,
  onRetry,
  onRetryPrediction,
  predictionStatuses,
  previews,
  ratings,
  selectedLineageId,
}: {
  captures?: ReadonlyMap<string, CaptureStatus> | undefined;
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined;
  disabledReason: string | null;
  error: string | null;
  hasMore: boolean;
  items: ReferenceRecord[];
  loading: boolean;
  loadingMore: boolean;
  messageCounts?: ReadonlyMap<string, number> | undefined;
  now: number;
  onLoadMore: () => void;
  onOpen: (lineageId: string) => void;
  onRate: ReferenceFeedProps["onRate"];
  onRetry: () => void;
  onRetryPrediction?: ((lineageId: string) => void) | undefined;
  predictionStatuses?: PredictionStatuses | undefined;
  previews: ReadonlyMap<string, ReferencePreview>;
  ratings?: RatingController | undefined;
  selectedLineageId: string;
}) {
  if (loading) return <div data-auto-accepted-list="loading"><ReferenceFeedSkeleton count={3} /></div>;
  if (error && !items.length) {
    return (
      <div className="space-y-3 rounded-[20px] bg-[var(--feed-card)] p-6 text-sm" data-auto-accepted-list="error" role="alert">
        <p>The automatically accepted references could not be read. {error}</p>
        <button className="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-4 font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={onRetry} type="button">
          <RefreshCwIcon aria-hidden="true" className="size-4" />Try again
        </button>
      </div>
    );
  }
  if (!items.length) {
    return (
      <div className="rounded-[20px] bg-[var(--feed-card)] p-8 text-center text-sm text-muted-foreground" data-auto-accepted-list="empty" data-auto-accepted-empty>
        <BotIcon aria-hidden="true" className="mx-auto mb-3 size-6" />
        <p className="mx-auto max-w-prose">{AUTO_ACCEPTED_EMPTY_TEXT}</p>
      </div>
    );
  }
  return (
    <div className="space-y-4" data-auto-accepted-list="ready">
      <p className="text-sm text-muted-foreground" data-auto-accepted-intro>
        These were accepted without an editor, newest first. Accept the ones you agree with, and say why if you like. Reject any you disagree with, and say why.
      </p>
      <div className={FEED_GRID} data-feed-grid>
        {items.map((reference) => {
          const lineageId = referenceLineageId(reference);
          const decision = decisions?.get(lineageId);
          return (
            <div className="flex min-w-0 flex-col gap-2" data-auto-accepted-item={lineageId} key={lineageId}>
              <FeedCard
                capture={captures?.get(lineageId)}
                decision={decision}
                disabledReason={disabledReason}
                item={scoreFeedItem(reference, decision)}
                lead={false}
                messageCount={messageCounts?.get(lineageId)}
                now={now}
                onOpen={() => onOpen(lineageId)}
                onRate={onRate}
                onRetryPrediction={onRetryPrediction ? () => onRetryPrediction(lineageId) : undefined}
                predictionLoading={false}
                predictionStatus={predictionStatuses?.get(lineageId)}
                preview={previews.get(lineageId)}
                ratings={ratings}
                selected={selectedLineageId === lineageId}
                visitRated={false}
              />
              <WhyAccepted decision={decision} reference={reference} />
            </div>
          );
        })}
      </div>
      {error ? (
        <p className="flex flex-wrap items-center gap-3 rounded-2xl bg-[var(--feed-card)] px-4 py-3 text-sm" role="alert">
          <span>More could not be read. {error}</span>
          <button className="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-4 font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={onRetry} type="button">
            <RefreshCwIcon aria-hidden="true" className="size-4" />Try again
          </button>
        </p>
      ) : null}
      <MoreSentinel hasMore={hasMore} itemCount={items.length} loadingMore={loadingMore} onLoadMore={onLoadMore} />
    </div>
  );
}
