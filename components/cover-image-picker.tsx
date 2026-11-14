"use client";

import { CheckIcon, CircleAlertIcon, ExternalLinkIcon, ImageOffIcon, RefreshCwIcon, ScaleIcon, SearchIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { OFFERED_LICENCES_TEXT } from "../lib/stock-images/licences";
import { creditLine } from "../lib/stock-images/cover";
import type { StockImageClient } from "../lib/stock-images/client";
import { deriveSearchTarget } from "../lib/stock-images/search-target";
import type { StockCandidate } from "../lib/stock-images/types";

export type PickerStatus = "loading" | "loaded" | "empty" | "error";

export type PickerViewProps = {
  status: PickerStatus;
  candidates: StockCandidate[];
  /** What is in the text box. Kept as typed when a search fails. */
  targetText: string;
  /** What the last request actually searched for, and whether the system worked it out. */
  searched: string;
  searchedFromStory: boolean;
  error: string | null;
  /** True when another four may exist for this search. */
  hasMore: boolean;
  pickingId: string | null;
  pickError: string | null;
  onTargetChange: (value: string) => void;
  onSearch: () => void;
  onReload: () => void;
  onRetry: () => void;
  onPick: (candidate: StockCandidate) => void;
  onClose: () => void;
};

function Tile({ candidate, busy, disabled, onPick }: { candidate: StockCandidate; busy: boolean; disabled: boolean; onPick: () => void }) {
  return (
    <li className="flex flex-col gap-2 rounded-xl bg-background p-2" data-stock-candidate={candidate.id}>
      {/* The picture comes straight from the source for the editor's preview only; the copy that readers see is made on Accept. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img alt={candidate.description || candidate.title} className="aspect-[4/3] w-full rounded-lg bg-muted object-cover" loading="lazy" src={candidate.imageUrl} />
      <div className="space-y-1 px-1 text-sm">
        <p className="font-medium leading-snug">{candidate.title}</p>
        {candidate.description ? <p className="line-clamp-2 text-xs text-muted-foreground">{candidate.description}</p> : null}
        <p className="flex items-start gap-1 text-xs text-muted-foreground" data-stock-credit>
          <ScaleIcon aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
          <span>{creditLine(candidate)}</span>
        </p>
        <a className="inline-flex items-center gap-1 text-xs underline underline-offset-2" href={candidate.sourceUrl} rel="noopener noreferrer" target="_blank">
          <ExternalLinkIcon aria-hidden="true" className="size-3" />
          File page on {candidate.sourceLabel}
        </a>
      </div>
      <Button data-stock-accept disabled={disabled} onClick={onPick} size="default" type="button">
        {busy ? <Spinner /> : <CheckIcon aria-hidden="true" />}
        {busy ? "Copying in…" : "Accept as cover"}
      </Button>
    </li>
  );
}

/** The picker's whole appearance, driven by props so every state can be shown and tested without a network. */
export function CoverImagePickerView(props: PickerViewProps) {
  const { status, candidates, targetText, searched, searchedFromStory, error, hasMore, pickingId, pickError } = props;
  const working = status === "loading" || pickingId !== null;
  return (
    <section aria-label="Cover image from Wikimedia Commons" className="space-y-3 rounded-2xl bg-muted p-3" data-cover-picker>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Cover image from Wikimedia Commons</h2>
        <Button data-stock-close onClick={props.onClose} size="xs" type="button" variant="ghost">
          <XIcon aria-hidden="true" />
          Give up
        </Button>
      </div>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!working) props.onSearch();
        }}
      >
        <label className="sr-only" htmlFor="stock-image-target">What to look for</label>
        <Input
          className="min-w-0 flex-1 basis-48 border-transparent bg-background dark:bg-background"
          data-stock-target
          id="stock-image-target"
          onChange={(event) => props.onTargetChange(event.target.value)}
          placeholder="Search words (optional)"
          value={targetText}
        />
        <Button data-stock-search disabled={working} size="default" type="submit">
          <SearchIcon aria-hidden="true" />
          Search
        </Button>
      </form>

      {searched ? (
        <p className="text-xs text-muted-foreground" data-stock-searched>
          Searched for <q>{searched}</q>{searchedFromStory ? ", worked out from the title and summary. Type your own words above to change it." : "."}
        </p>
      ) : null}

      {status === "loading" ? (
        <div role="status">
          <p className="flex items-center gap-2 text-sm" data-stock-loading>
            <Spinner />
            Looking on Wikimedia Commons…
          </p>
          <ul aria-hidden="true" className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((slot) => (
              <li className="h-48 animate-pulse rounded-xl bg-background" key={slot} />
            ))}
          </ul>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-background p-3 text-sm" data-stock-error role="alert">
          <CircleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
          <p className="flex-1">{error ?? "The search failed."} What you typed is kept.</p>
          <Button data-stock-retry onClick={props.onRetry} size="sm" type="button" variant="secondary" className="bg-background hover:bg-background/70">
            <RefreshCwIcon aria-hidden="true" />
            Try again
          </Button>
        </div>
      ) : null}

      {status === "empty" ? (
        <div className="flex items-start gap-2 rounded-xl bg-background p-3 text-sm" data-stock-empty role="status">
          <ImageOffIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {searched ? (
            <p>
              Nothing found for <q>{searched}</q> with a licence we can use ({OFFERED_LICENCES_TEXT}). Try other words, or give up and choose another kind of cover.
            </p>
          ) : (
            <p>The Story has no title or summary to search from yet. Type what to look for above.</p>
          )}
        </div>
      ) : null}

      {status === "loaded" || (status === "error" && candidates.length > 0) ? (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" data-stock-candidates>
          {candidates.map((candidate) => (
            <Tile busy={pickingId === candidate.id} candidate={candidate} disabled={working} key={candidate.id} onPick={() => props.onPick(candidate)} />
          ))}
        </ul>
      ) : null}

      {pickError ? (
        <p className="flex items-center gap-2 text-sm text-destructive" data-stock-pick-error role="alert">
          <CircleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
          {pickError}
        </p>
      ) : null}

      {status === "loaded" || status === "empty" ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button data-stock-reload disabled={working || !hasMore} onClick={props.onReload} size="sm" type="button" variant="secondary" className="bg-background hover:bg-background/70">
            <RefreshCwIcon aria-hidden="true" />
            Reload: four more
          </Button>
          {!hasMore ? <p className="text-xs text-muted-foreground" data-stock-no-more>No more results for this search. Change the words and search again.</p> : null}
        </div>
      ) : null}
    </section>
  );
}

export type PickedImage = Awaited<ReturnType<StockImageClient["fetchPicked"]>>;

/**
 * The cover picker on a Story. Four options at a time from one source; Accept one, reload for four more, search with the editor's own words,
 * or give up. Pictures already shown never come back during this run. Nothing is saved here: `onPicked` hands the copied file to the editor,
 * whose own save creates the Story version.
 */
export function CoverImagePicker({
  client, title, summary, onPicked, onClose,
}: {
  client: StockImageClient;
  title: string;
  summary: string;
  onPicked: (picked: PickedImage) => Promise<void>;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<PickerStatus>("loading");
  const [candidates, setCandidates] = useState<StockCandidate[]>([]);
  const [targetText, setTargetText] = useState("");
  const [searched, setSearched] = useState("");
  const [fromStory, setFromStory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>("");
  const [pickingId, setPickingId] = useState<string | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const shown = useRef(new Set<string>());
  const sequence = useRef(0);
  const last = useRef<{ target: string; cursor: string; derived: boolean }>({ target: "", cursor: "", derived: false });

  const run = useCallback(async (target: string, at: string, derived: boolean) => {
    last.current = { target, cursor: at, derived };
    const mine = ++sequence.current;
    setSearched(target);
    setFromStory(derived);
    setPickError(null);
    if (!target) {
      setStatus("empty");
      setCandidates([]);
      setCursor(null);
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      const result = await client.search({ target, cursor: at, exclude: [...shown.current] });
      if (mine !== sequence.current) return;
      result.candidates.forEach((candidate) => shown.current.add(candidate.id));
      setCandidates(result.candidates);
      setCursor(result.nextCursor);
      setStatus(result.candidates.length > 0 ? "loaded" : "empty");
    } catch (failure) {
      if (mine !== sequence.current) return;
      setError(failure instanceof Error ? failure.message : "The search failed.");
      setStatus("error");
    }
  }, [client]);

  const startWith = useCallback((typed: string) => {
    const words = typed.trim();
    void run(words || deriveSearchTarget(title, summary), "", !words);
  }, [run, title, summary]);

  const firstRun = useRef(false);
  useEffect(() => {
    if (firstRun.current) return;
    firstRun.current = true;
    startWith("");
  }, [startWith]);

  return (
    <CoverImagePickerView
      candidates={candidates}
      error={error}
      hasMore={cursor !== null}
      onClose={onClose}
      onPick={(candidate) => {
        setPickingId(candidate.id);
        setPickError(null);
        client
          .fetchPicked(candidate)
          .then((picked) => onPicked(picked))
          .catch((failure: unknown) => setPickError(failure instanceof Error ? failure.message : "That image could not be copied in. Choose another or try again."))
          .finally(() => setPickingId(null));
      }}
      onReload={() => void run(last.current.target, cursor ?? "", last.current.derived)}
      onRetry={() => void run(last.current.target, last.current.cursor, last.current.derived)}
      onSearch={() => startWith(targetText)}
      onTargetChange={setTargetText}
      pickError={pickError}
      pickingId={pickingId}
      searched={searched}
      searchedFromStory={fromStory}
      status={status}
      targetText={targetText}
    />
  );
}
