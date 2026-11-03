"use client";

import { CheckIcon, CircleCheckIcon, CircleXIcon, Columns2Icon, FileTextIcon, HashIcon, LightbulbIcon, LinkIcon, Loader2Icon, NewspaperIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { CONNECTION_WORDS, connectionHref, waysText, type ConnectionKind, type StoryVariationView } from "../lib/story-variations";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";
import { resolveVariationSource, type VariationSource } from "./story-variations-client";

/**
 * The variations of a Story side by side (docs/story-variations.md, PPY-9e7a4a). Each card leads with its point and shows its headline, deck and what it
 * connects to, as links to the Reference, Story or concept. An editor accepts a variation (its wording becomes the Story's next version, recorded with
 * `variationId`) or rejects it, with an optional reason. Accept and Reject are always words with icons, never colour alone. Cards sit side by side on a wide
 * pane and stack on a narrow one; flat rounded backgrounds, no outlines.
 */

const CONNECTION_ICON: Record<ConnectionKind, typeof LinkIcon> = { reference: LinkIcon, story: NewspaperIcon, concept: HashIcon };
const BUTTON = "inline-flex min-h-12 flex-1 items-center justify-center gap-1.5 rounded-[16px] px-3 text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring";
const QUIET = "bg-[var(--feed-control)] text-foreground hover:bg-[var(--feed-control)]/70";
const CHOSEN = "bg-[var(--primary)] text-[var(--primary-foreground)]";

function StatusChip({ status }: { status: StoryVariationView["status"] }) {
  const Icon = status === "accepted" ? CircleCheckIcon : status === "rejected" ? CircleXIcon : LightbulbIcon;
  const word = status === "accepted" ? "Accepted" : status === "rejected" ? "Rejected" : "On offer";
  return <span className="inline-flex items-center gap-1 rounded-full bg-[var(--feed-footer)] px-2.5 py-1 text-xs font-semibold" data-variation-status-chip><Icon aria-hidden="true" className="size-3.5" />{word}</span>;
}

export function VariationCard({ variation, demo, disabledReason, onDecide }: {
  variation: StoryVariationView; demo: boolean; disabledReason: string | null;
  onDecide: (variation: StoryVariationView, decision: "accepted" | "rejected", reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState(variation.decisionReason ?? "");
  const [busy, setBusy] = useState<"accepted" | "rejected" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bodyOpen, setBodyOpen] = useState(false);
  useEffect(() => { setReason(variation.decisionReason ?? ""); }, [variation.decisionReason, variation.status]);
  const decide = async (decision: "accepted" | "rejected") => {
    if (busy || disabledReason) return;
    setBusy(decision);
    setError(null);
    try { await onDecide(variation, decision, reason); } catch (failure) { setError(failure instanceof Error ? failure.message : "The decision could not be saved."); } finally { setBusy(null); }
  };
  const check = variation.pointCheck;
  return (
    <article className="grid content-start gap-3 rounded-[20px] bg-[var(--feed-control)] p-4 font-sans" data-story-variation={variation.id} data-variation-number={variation.variationNumber} data-variation-status={variation.status}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Variation {variation.variationNumber}</h3>
        <StatusChip status={variation.status} />
      </header>
      <div className="grid gap-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Point</span>
        <p className="break-words text-base font-semibold leading-snug text-foreground" data-variation-point>{variation.point}</p>
      </div>
      <div className="grid gap-1">
        <p className="break-words text-lg font-bold leading-tight tracking-tight text-foreground" data-variation-headline>{variation.headline}</p>
        {variation.deck ? <p className="break-words text-sm text-muted-foreground" data-variation-deck>{variation.deck}</p> : null}
      </div>
      <div className="grid gap-1.5">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Connects to</span>
        <ul className="grid gap-1.5" data-variation-connections>
          {variation.connections.map((connection) => {
            const Icon = CONNECTION_ICON[connection.kind];
            return (
              <li key={`${connection.kind}:${connection.id}`}>
                <Link className="block rounded-[14px] bg-[var(--feed-footer)] p-2.5 text-sm !text-foreground !no-underline outline-none transition-colors hover:bg-[var(--feed-footer)]/70 focus-visible:ring-2 focus-visible:ring-ring" data-variation-connection={connection.kind} href={connectionHref(connection, demo)}>
                  <span className="flex items-start gap-2">
                    <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    <span className="min-w-0">
                      <span className="block break-words font-medium leading-snug"><span className="text-muted-foreground">{CONNECTION_WORDS[connection.kind]}: </span>{connection.title}</span>
                      {connection.how ? <span className="block text-xs text-muted-foreground">{connection.how}</span> : null}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
      {check ? (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-variation-point-check>
          <CheckIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>Point check: {check.verdict === "adds" ? "it adds a claim of its own" : check.verdict}{check.claim ? `: ${check.claim}` : ""}</span>
        </p>
      ) : null}
      {variation.bodyMarkus ? (
        <div className="grid gap-2">
          <button aria-expanded={bodyOpen} className="inline-flex min-h-10 w-fit items-center gap-1.5 rounded-full bg-[var(--feed-footer)] px-3 text-xs font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring" data-variation-body-toggle onClick={() => setBodyOpen((open) => !open)} type="button">
            <FileTextIcon aria-hidden="true" className="size-3.5" />{bodyOpen ? "Hide the body" : "Read the body"}
          </button>
          {bodyOpen ? <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-[14px] bg-[var(--feed-footer)] p-3 text-xs leading-relaxed" data-variation-body tabIndex={0}>{variation.bodyMarkus}</pre> : null}
        </div>
      ) : null}
      <section aria-label={`Decide variation ${variation.variationNumber}`} className="grid gap-2 rounded-[16px] bg-[var(--feed-footer)] p-2.5" data-variation-decision>
        {variation.status !== "offered" ? (
          <p className="text-xs text-muted-foreground" data-variation-decided>
            {variation.status === "accepted" ? "Accepted" : "Rejected"}{variation.decidedByLabel ? ` by ${variation.decidedByLabel}` : ""}.
            {variation.status === "accepted" ? " Its wording is the Story's current version." : ""}
          </p>
        ) : null}
        <AutoGrowTextarea
          aria-label={`Why? (optional), variation ${variation.variationNumber}`}
          className="block min-h-16 w-full rounded-[14px] bg-[var(--feed-control)] p-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          data-variation-reason
          onChange={(event) => setReason(event.target.value)}
          placeholder="Why? Optional. Your reason is kept with the variation."
          value={reason}
        />
        <div className="flex gap-2">
          <button aria-label={`Accept variation ${variation.variationNumber}`} aria-pressed={variation.status === "accepted"} className={cn(BUTTON, variation.status === "accepted" ? CHOSEN : QUIET, (busy || disabledReason) && "opacity-60")} data-variation-accept disabled={Boolean(busy) || Boolean(disabledReason) || variation.status === "accepted"} onClick={() => void decide("accepted")} type="button">
            {busy === "accepted" ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <CheckIcon aria-hidden="true" className="size-4" />}
            {busy === "accepted" ? "Saving…" : "Accept"}
          </button>
          <button aria-label={`Reject variation ${variation.variationNumber}`} aria-pressed={variation.status === "rejected"} className={cn(BUTTON, variation.status === "rejected" ? CHOSEN : QUIET, busy && "opacity-60")} data-variation-reject disabled={Boolean(busy) || variation.status === "rejected"} onClick={() => void decide("rejected")} type="button">
            {busy === "rejected" ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <XIcon aria-hidden="true" className="size-4" />}
            {busy === "rejected" ? "Saving…" : "Reject"}
          </button>
        </div>
        {disabledReason ? <p className="text-xs text-muted-foreground" data-variation-disabled-reason>{disabledReason}</p> : null}
        {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
      </section>
    </article>
  );
}

/** The cards of one Story's variations, in the order they were offered. Nothing renders when there are none. */
export function StoryVariationCards({ variations, demo = false, disabledReason = null, onDecide }: {
  variations: readonly StoryVariationView[]; demo?: boolean; disabledReason?: string | null;
  onDecide: (variation: StoryVariationView, decision: "accepted" | "rejected", reason: string) => Promise<void>;
}) {
  if (!variations.length) return null;
  return (
    <section aria-label="Variations of this idea" className="@container grid gap-3" data-feed-surface data-story-variations={variations.length}>
      <header className="grid gap-0.5">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><Columns2Icon aria-hidden="true" className="size-4" />Variations<span className="font-normal text-muted-foreground" data-variations-count> · {waysText(variations.length)}</span></h2>
        <p className="text-xs text-muted-foreground" data-variations-help>
          {variations.length === 1 ? "Only one way to connect this was found. " : ""}Accept one and its wording becomes the next version of the Story. Accepting another puts the earlier one back on offer.
        </p>
      </header>
      <div className={cn("grid grid-cols-1 gap-3", variations.length > 1 && "@2xl:grid-cols-2", variations.length > 2 && "@5xl:grid-cols-3")} data-variation-grid>
        {variations.map((variation) => <VariationCard demo={demo} disabledReason={disabledReason} key={variation.id} onDecide={onDecide} variation={variation} />)}
      </div>
    </section>
  );
}

/**
 * The variations of one Story, read from the API (or the preview) and decided there. `applyWording` is what accepting does to the Story: it saves the
 * variation's wording as the Story's next version; it runs before the variation is marked accepted, so a wording that could not be saved is not
 * recorded as accepted. `reloadKey` makes the panel read again (the Story changed).
 */
export function StoryVariationsPanel({ lineageId, demo = false, decidedBy, applyWording, disabledReason = null, reloadKey = 0, source, onChanged }: {
  lineageId: string; demo?: boolean; decidedBy: string; disabledReason?: string | null; reloadKey?: number; source?: VariationSource; onChanged?: () => void;
  applyWording: (variation: StoryVariationView, reason: string) => Promise<void>;
}) {
  const via = source ?? resolveVariationSource(demo);
  const [variations, setVariations] = useState<StoryVariationView[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    via.load(lineageId).then((rows) => { if (live) { setVariations(rows); setLoadError(null); } }, (failure: unknown) => { if (live) setLoadError(failure instanceof Error ? failure.message : "The variations could not be read."); });
    return () => { live = false; };
  }, [lineageId, reloadKey, version, via]);
  const onDecide = useCallback(async (variation: StoryVariationView, decision: "accepted" | "rejected", reason: string) => {
    if (decision === "accepted") await applyWording(variation, reason);
    await via.decide(variation, decision, { label: decidedBy }, reason, variations);
    setVersion((current) => current + 1);
    onChanged?.();
  }, [applyWording, decidedBy, onChanged, variations, via]);
  if (loadError && !variations.length) return <p className="text-xs text-muted-foreground" data-variations-unavailable role="status">The variations could not be read right now.</p>;
  return <StoryVariationCards demo={demo} disabledReason={disabledReason} onDecide={onDecide} variations={variations} />;
}
