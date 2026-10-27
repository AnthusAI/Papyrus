"use client";

import {
  CheckIcon,
  CircleCheckIcon,
  CircleXIcon,
  InfoIcon,
  Loader2Icon,
  MinusIcon,
  NewspaperIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import { REFERENCE_REJECTION_REASON_CODES, normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import {
  referenceDisplayTime,
  EARLIER_AFTER_TAUS,
  MINIMUM_FRESHNESS_EXAMPLES,
  type FeedItem,
  type FeedFreshness,
  type ReferenceFeedPartition,
  type ReferenceFeedTabKey,
} from "../lib/reference-feed-ranking";
import { referenceDek, referenceSourceHost, formatFeedAge, type ReferencePreview } from "../lib/reference-preview";
import { referenceDisplayTitle } from "../lib/newsroom-references";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { predictionFromDecision, type ReviewChoice } from "./reference-review-card";

const REASON_LABELS: Record<ReferenceRejectionReasonCode, string> = {
  out_of_scope: "Out of scope",
  policy_exclusion: "Policy exclusion",
  duplicate: "Duplicate",
  low_quality: "Low quality",
  unavailable: "Unavailable",
  provenance: "Provenance",
  other: "Other",
};

const TAB_LABELS: Record<ReferenceFeedTabKey, string> = { feed: "Feed", rated: "Rated", earlier: "Earlier" };

export type ReferenceFeedProps = {
  /** Read-only reason shown in words when answering is not possible yet (for example while the session is confirmed). */
  disabledReason?: string | null;
  /** True while the first read is in flight: cards are skeletons. */
  loading?: boolean;
  now: number;
  onOpen: (lineageId: string) => void;
  onRate: (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) => Promise<void> | void;
  onVisitRated: (lineageId: string) => void;
  onTabChange: (tab: ReferenceFeedTabKey) => void;
  /** The ranked tabs, from `partitionReferenceFeed`. */
  partition: ReferenceFeedPartition;
  predictionLoading?: boolean;
  previews: ReadonlyMap<string, ReferencePreview>;
  selectedLineageId?: string;
  /** True when the cards are a saved copy that is being refreshed. */
  stale?: boolean;
  tab: ReferenceFeedTabKey;
  visitRated: ReadonlySet<string>;
};

/** Pulsing placeholder cards: the page shell is on screen at once, with no "checking" screen in front of it. */
export function ReferenceFeedSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading references" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" data-reference-feed-skeleton role="status">
      {Array.from({ length: count }, (_, index) => (
        <div className={cn("overflow-hidden rounded-2xl border bg-card", index === 0 && "sm:col-span-2")} key={index}>
          <div className={cn("animate-pulse bg-muted", index === 0 ? "aspect-[2/1]" : "aspect-[16/9]")} />
          <div className="space-y-3 p-4">
            <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
            <div className="h-5 w-11/12 animate-pulse rounded bg-muted" />
            <div className="h-5 w-2/3 animate-pulse rounded bg-muted" />
            <div className="h-3 w-5/6 animate-pulse rounded bg-muted" />
            <div className="flex gap-2 pt-2"><div className="h-9 flex-1 animate-pulse rounded-md bg-muted" /><div className="h-9 flex-1 animate-pulse rounded-md bg-muted" /></div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** A tile with the source name, for a Reference whose page has no usable preview image. */
function FallbackTile({ host }: { host: string | null }) {
  return (
    <div className="flex size-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-muted to-muted/40 p-4 text-muted-foreground" data-feed-image-fallback>
      <NewspaperIcon aria-hidden="true" className="size-8" />
      <span className="max-w-full truncate text-sm font-medium">{host ?? "Source"}</span>
    </div>
  );
}

/** Lazy image in a fixed frame: a blurred skeleton until it loads, the fallback tile when it never does. */
function FeedImage({ host, lead, src }: { host: string | null; lead: boolean; src: string | null }) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">(src ? "loading" : "failed");
  const ref = useRef<HTMLImageElement | null>(null);
  useEffect(() => { setState(src ? "loading" : "failed"); }, [src]);
  useEffect(() => {
    // A cached image can finish before React attaches onLoad.
    const element = ref.current;
    if (element?.complete && element.naturalWidth > 0) setState("loaded");
  }, [src]);
  return (
    <div className={cn("relative w-full overflow-hidden bg-muted", lead ? "aspect-[2/1] xl:aspect-[21/9]" : "aspect-[16/9]")} data-feed-image data-feed-image-state={state}>
      {state === "loading" ? <div aria-hidden="true" className="absolute inset-0 animate-pulse bg-gradient-to-br from-muted via-muted-foreground/10 to-muted blur-sm" data-feed-image-placeholder /> : null}
      {src && state !== "failed" ? (
        // The source site chose this picture; an <img> keeps it out of our image optimizer and out of its referrer log.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className={cn("absolute inset-0 size-full object-cover transition-opacity duration-500", state === "loaded" ? "opacity-100" : "opacity-0")}
          decoding="async"
          loading="lazy"
          onError={() => setState("failed")}
          onLoad={() => setState("loaded")}
          ref={ref}
          referrerPolicy="no-referrer"
          src={src}
        />
      ) : null}
      {state === "failed" ? <FallbackTile host={host} /> : null}
    </div>
  );
}

/** A mark for the source: its own favicon when it loads, else the first letter on a tile. */
function SourceMark({ host }: { host: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!host) return <span aria-hidden="true" className="inline-flex size-4 items-center justify-center rounded-sm bg-muted text-muted-foreground"><NewspaperIcon className="size-3" /></span>;
  return failed ? (
    <span aria-hidden="true" className="inline-flex size-4 items-center justify-center rounded-sm bg-muted text-[0.625rem] font-semibold uppercase text-muted-foreground" data-feed-source-mark>{host[0]}</span>
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" className="size-4 rounded-sm" data-feed-source-mark height={16} loading="lazy" onError={() => setFailed(true)} referrerPolicy="no-referrer" src={`https://${host}/favicon.ico`} width={16} />
  );
}

function percent(confidence: number | null): string | null {
  return confidence === null ? null : `${Math.round(confidence * 100)}%`;
}

/** The Cyclotron's read-only answer: Accept or Reject with its confidence, then match or miss once a person has answered. */
function PredictionChip({ answer, decision, loading }: { answer: ReviewChoice | null; decision: RelevanceDecisionView | undefined; loading: boolean }) {
  if (!decision) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground" data-cyclotron-state={loading ? "loading" : "none"}>
        {loading ? <Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" /> : <MinusIcon aria-hidden="true" className="size-3.5" />}
        {loading ? "Predicting…" : "No prediction"}
      </span>
    );
  }
  const prediction = predictionFromDecision(decision);
  if (prediction.state !== "ready") return null;
  const matched = answer ? prediction.choice === answer : null;
  const verdict = matched === null ? null : matched ? "match" : "miss";
  const Icon = verdict === "match" ? CircleCheckIcon : verdict === "miss" ? CircleXIcon : prediction.choice === "accept" ? CheckIcon : XIcon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium",
        verdict === null && "bg-muted/60",
        verdict === "match" && "border-green-700 bg-green-100 text-green-950 dark:border-green-400 dark:bg-green-950 dark:text-green-100",
        verdict === "miss" && "border-red-700 bg-red-100 text-red-950 dark:border-red-400 dark:bg-red-950 dark:text-red-100",
      )}
      data-cyclotron-choice={prediction.choice}
      data-predicted
      data-verdict={verdict ?? undefined}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      <span>Cyclotron: {prediction.choice === "accept" ? "Accept" : "Reject"}{percent(prediction.confidence) ? ` ${percent(prediction.confidence)}` : ""}</span>
      {verdict ? <span data-verdict-word>{verdict === "match" ? "· Match" : "· Miss"}</span> : null}
      {verdict ? <span className="sr-only">{verdict === "match" ? ", matches your answer" : ", differs from your answer"}</span> : null}
    </span>
  );
}

type RateState = { phase: "idle" | "saving" | "saved" | "error" | "reason"; message?: string };

function FeedCard({
  decision,
  disabledReason,
  item,
  lead,
  now,
  onOpen,
  onRate,
  predictionLoading,
  preview,
  selected,
  visitRated,
}: {
  decision: RelevanceDecisionView | undefined;
  disabledReason: string | null;
  item: FeedItem;
  lead: boolean;
  now: number;
  onOpen: () => void;
  onRate: ReferenceFeedProps["onRate"];
  predictionLoading: boolean;
  preview: ReferencePreview | undefined;
  selected: boolean;
  visitRated: boolean;
}) {
  const { reference } = item;
  const titleId = useId();
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const answer: ReviewChoice | null = status === "accepted" ? "accept" : status === "rejected" ? "reject" : null;
  const [rate, setRate] = useState<RateState>({ phase: "idle" });
  const inFlight = useRef(false);
  const host = referenceSourceHost(reference);
  const site = preview?.siteName ?? host;
  const dek = referenceDek(reference, preview);
  const age = formatFeedAge(referenceDisplayTime(reference), now);

  async function save(choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null) {
    if (disabledReason || inFlight.current) return;
    inFlight.current = true;
    setRate({ phase: "saving" });
    try {
      await onRate(reference, choice, reasonCode);
      setRate({ phase: "saved" });
    } catch (failure) {
      setRate({ phase: "error", message: failure instanceof Error ? failure.message : "Your answer could not be saved. Tap it again to retry." });
    } finally {
      inFlight.current = false;
    }
  }

  function choose(choice: ReviewChoice) {
    if (disabledReason) return;
    if (answer === choice) return; // the chosen answer never unselects itself; the other choice is the undo
    if (choice === "reject") { setRate({ phase: "reason" }); return; }
    void save("accept", null);
  }

  return (
    <article
      aria-labelledby={titleId}
      className={cn(
        "group flex flex-col overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition-shadow hover:shadow-md",
        lead && "sm:col-span-2",
        selected && "ring-2 ring-foreground",
      )}
      data-feed-card={item.lineageId}
      data-feed-lead={lead || undefined}
      data-feed-rated={answer ?? undefined}
      data-feed-visit-rated={visitRated || undefined}
      data-newsroom-card-id={item.lineageId}
    >
      <button
        aria-label={`Open: ${referenceDisplayTitle(reference)}`}
        className="flex flex-1 flex-col text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-feed-open
        onClick={onOpen}
        type="button"
      >
        <FeedImage host={host} lead={lead} src={preview?.imageUrl ?? null} />
        <span className="flex flex-1 flex-col gap-2 p-4">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground" data-feed-source>
            <SourceMark host={host} />
            <span className="truncate font-medium text-foreground/80">{site ?? "Unknown source"}</span>
            {age ? <><span aria-hidden="true">·</span><time dateTime={new Date(referenceDisplayTime(reference) ?? now).toISOString()} title={new Date(referenceDisplayTime(reference) ?? now).toLocaleString()}>{age}</time></> : null}
          </span>
          <span className={cn("font-semibold leading-snug tracking-tight text-foreground", lead ? "line-clamp-3 text-xl sm:text-2xl lg:text-3xl" : "line-clamp-3 text-base")} data-feed-title id={titleId}>
            {referenceDisplayTitle(reference)}
          </span>
          {dek ? <span className={cn("text-muted-foreground", lead ? "line-clamp-3 text-base" : "line-clamp-2 text-sm")} data-feed-dek>{dek}</span> : null}
        </span>
      </button>

      <div className="space-y-2 border-t bg-muted/20 p-3" data-feed-actions>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <PredictionChip answer={answer} decision={decision} loading={predictionLoading} />
          <span aria-live="polite" className="inline-flex min-h-5 items-center gap-1 text-xs text-muted-foreground" data-feed-saved role="status">
            {rate.phase === "saving" ? <><Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Saving…</> : null}
            {rate.phase === "saved" || (visitRated && rate.phase === "idle" && answer) ? <><CheckIcon aria-hidden="true" className="size-3.5" />Saved</> : null}
          </span>
        </div>
        <div className="flex items-center gap-2" data-review-row="you">
          <span className="w-9 shrink-0 text-xs font-semibold">You</span>
          {(["accept", "reject"] as const).map((choice) => {
            const on = answer === choice;
            return (
              <Button
                aria-disabled={disabledReason ? true : undefined}
                aria-pressed={on}
                className="min-h-9 flex-1"
                data-review-choice={choice}
                key={choice}
                onClick={() => choose(choice)}
                size="sm"
                type="button"
                variant={on ? (choice === "accept" ? "default" : "destructive") : "outline"}
              >
                {on ? <CheckIcon aria-hidden="true" className="size-4" /> : choice === "accept" ? <CheckIcon aria-hidden="true" className="size-4 opacity-50" /> : <XIcon aria-hidden="true" className="size-4 opacity-50" />}
                {choice === "accept" ? "Accept" : "Reject"}
              </Button>
            );
          })}
        </div>
        {disabledReason ? <p className="text-xs text-muted-foreground" data-review-disabled-reason>{disabledReason}</p> : null}
        {rate.phase === "reason" ? (
          <div className="space-y-1.5" data-review-reasons>
            <p className="text-xs font-medium">Reason for rejecting. Choose one to save your Reject.</p>
            <div className="flex flex-wrap gap-1.5">
              {REFERENCE_REJECTION_REASON_CODES.map((code) => (
                <Button className="h-8 px-2.5 text-xs" data-review-reason={code} key={code} onClick={() => void save("reject", code)} size="sm" type="button" variant="outline">
                  {REASON_LABELS[code]}
                </Button>
              ))}
              <Button className="h-8 px-2.5 text-xs" onClick={() => setRate({ phase: "idle" })} size="sm" type="button" variant="ghost">Cancel</Button>
            </div>
          </div>
        ) : null}
        {rate.phase === "error" ? <p className="text-xs text-destructive" role="alert">{rate.message}</p> : null}
      </div>
    </article>
  );
}

function plainDays(days: number): string {
  if (days < 1) return `${Math.max(1, Math.round(days * 24))} hours`;
  return `${days < 10 ? days.toFixed(1).replace(/\.0$/, "") : Math.round(days)} days`;
}

/** The plain-words recipe, with this site's own learned numbers in it. */
function RankingPopover({ freshness }: { freshness: FeedFreshness }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) { if (event.key === "Escape") setOpen(false); return; }
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className="relative" ref={root}>
      <Button aria-controls={panelId} aria-expanded={open} aria-label="How this feed is ranked" className="min-h-9" data-feed-ranking-info onClick={() => setOpen((current) => !current)} size="sm" type="button" variant="ghost">
        <InfoIcon aria-hidden="true" className="size-4" />
        <span className="hidden sm:inline">How this feed is ranked</span>
        <span className="sm:hidden">Ranking</span>
      </Button>
      {open ? (
        <div className="fixed inset-x-4 bottom-24 z-30 max-h-[70dvh] space-y-3 overflow-y-auto rounded-xl border bg-popover p-4 text-sm text-popover-foreground shadow-xl sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:mt-2 sm:w-[22rem]" data-feed-ranking-panel id={panelId} role="dialog" aria-label="How this feed is ranked">
          <p className="font-semibold">A feed run by algorithms you control</p>
          <ol className="list-decimal space-y-2 pl-5">
            <li><strong>Best bets first.</strong> The Cyclotron predicts Accept or Reject and how sure it is. The items it expects you to Accept most surely come first. The ones it expects you to Reject most surely come last. Items with no prediction sit in the middle.</li>
            <li><strong>Confidence counts.</strong> An Accept at 90% ranks above an Accept at 60%.</li>
            <li><strong>Age fades a prediction toward &ldquo;not sure&rdquo;.</strong> Older items drift toward the middle, never to the bottom. {freshness.tauDays !== null && freshness.medianAgeDays !== null
              ? <>A prediction loses half its pull every {plainDays(freshness.medianAgeDays)}, the typical age of the {freshness.examples} items you accepted.</>
              : <>Age does not change the order yet. The pace is learned from the items you accept, and so far there are {freshness.examples} of the {MINIMUM_FRESHNESS_EXAMPLES} needed.</>}</li>
            <li><strong>Earlier.</strong> {freshness.tauDays !== null
              ? <>Unrated items older than {plainDays(freshness.tauDays * EARLIER_AFTER_TAUS)} move to Earlier at the bottom. You can still rate them. Nothing is deleted.</>
              : <>Once the pace is learned, unrated items past three times that pace move to Earlier at the bottom. Nothing is deleted.</>}</li>
            <li><strong>Your answers stay put.</strong> A card you rate stays where it is for this visit. Next time it is under Rated.</li>
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function CardGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" data-feed-grid>{children}</div>;
}

export function ReferenceFeed({
  disabledReason = null,
  loading = false,
  now,
  onOpen,
  onRate,
  onTabChange,
  onVisitRated,
  partition,
  predictionLoading = false,
  previews,
  selectedLineageId = "",
  stale = false,
  tab,
  visitRated,
}: ReferenceFeedProps) {
  const counts: Record<ReferenceFeedTabKey, number> = { feed: partition.feed.length, rated: partition.rated.length, earlier: partition.earlier.length };

  const renderCard = (item: FeedItem, lead: boolean) => (
    <FeedCard
      decision={item.decision}
      disabledReason={disabledReason}
      item={item}
      key={item.lineageId}
      lead={lead}
      now={now}
      onOpen={() => onOpen(item.lineageId)}
      onRate={async (reference, choice, reasonCode) => { onVisitRated(item.lineageId); await onRate(reference, choice, reasonCode); }}
      predictionLoading={predictionLoading}
      preview={previews.get(item.lineageId)}
      selected={selectedLineageId === item.lineageId}
      visitRated={visitRated.has(item.lineageId)}
    />
  );

  const empty = (label: string) => (
    <div className="rounded-2xl border border-dashed p-8 text-center text-sm text-muted-foreground" data-feed-empty>{label}</div>
  );

  return (
    <div className="space-y-4" data-reference-feed data-feed-tab={tab}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div aria-label="Feed sections" className="inline-flex rounded-xl bg-muted/60 p-1" role="tablist">
          {(Object.keys(TAB_LABELS) as ReferenceFeedTabKey[]).map((key) => (
            <button
              aria-selected={tab === key}
              className={cn(
                "inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors",
                tab === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
              data-feed-tab-button={key}
              key={key}
              onClick={() => onTabChange(key)}
              role="tab"
              type="button"
            >
              {TAB_LABELS[key]}
              <span className={cn("rounded-full px-1.5 text-xs tabular-nums", tab === key ? "bg-muted" : "bg-muted/70")} data-feed-tab-count>{counts[key]}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {stale ? (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" data-feed-stale role="status">
              <Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Showing your last view while it updates
            </span>
          ) : null}
          <RankingPopover freshness={partition.freshness} />
        </div>
      </div>

      {loading ? <ReferenceFeedSkeleton /> : (
        <div role="tabpanel">
          {tab === "feed" ? (
            <div className="space-y-8">
              {partition.feed.length ? (
                <CardGrid>
                  {partition.feed.map((item, index) => renderCard(item, index === 0))}
                </CardGrid>
              ) : empty(counts.rated || counts.earlier ? "You are all caught up. Check Earlier and Rated." : "No references yet.")}
              {partition.earlier.length ? (
                <section aria-labelledby="feed-earlier-heading" className="space-y-3" data-feed-earlier>
                  <div className="flex items-baseline justify-between gap-2 border-t pt-6">
                    <h3 className="text-lg font-semibold tracking-tight" id="feed-earlier-heading">Earlier</h3>
                    <p className="text-xs text-muted-foreground">Unrated and past their freshness. Still yours to rate.</p>
                  </div>
                  <CardGrid>{partition.earlier.map((item) => renderCard(item, false))}</CardGrid>
                </section>
              ) : null}
            </div>
          ) : null}
          {tab === "rated" ? (partition.rated.length ? <CardGrid>{partition.rated.map((item) => renderCard(item, false))}</CardGrid> : empty("Nothing rated yet. Your Accepts and Rejects collect here, newest first.")) : null}
          {tab === "earlier" ? (partition.earlier.length ? <CardGrid>{partition.earlier.map((item) => renderCard(item, false))}</CardGrid> : empty("Nothing has aged out. Unrated items that fall past their freshness collect here."))  : null}
        </div>
      )}
    </div>
  );
}
