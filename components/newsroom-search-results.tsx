"use client";

import { CheckIcon, CircleCheckIcon, CircleDashedIcon, CircleXIcon, ListIcon, Loader2Icon, QuoteIcon, RefreshCwIcon, SearchIcon, SparklesIcon, TypeIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import type { ReferenceRecord } from "../lib/category-repository";
import { referenceDisplayTitle } from "../lib/newsroom-references";
import { referenceDisplayTime } from "../lib/reference-feed-ranking";
import { formatFeedAge, referenceSourceHost } from "../lib/reference-preview";
import {
  SEARCH_KIND_LABEL,
  SEARCH_PAGE_SIZE,
  SEARCH_STATUS_CHOICES,
  bothLanesFailed,
  laneNotice,
  normalizeSearchQuery,
  searchKindExplanation,
  searchResultKind,
  searchStatusWord,
  showForStatus,
  splitSearchResults,
  type ReferenceSearchMatch,
  type ReferenceSearchPage,
  type ReferenceSearchReader,
  type SearchResultKind,
  type SearchStatusChoice,
} from "../lib/reference-search";
import { cn } from "@/lib/utils";

const PILL = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full px-4 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring";
const STATUS_LABEL: Record<SearchStatusChoice, string> = { any: "Any", pending: "Pending", accepted: "Accepted", rejected: "Rejected" };
const STATUS_ICON = { any: ListIcon, pending: CircleDashedIcon, accepted: CircleCheckIcon, rejected: CircleXIcon } as const;
const KIND_ICON: Record<SearchResultKind, typeof TypeIcon> = { title: TypeIcon, word: QuoteIcon, related: SparklesIcon };

export type NewsroomSearchResultsProps = {
  /** The query the page opened with (`?q=`). */
  initialQuery: string;
  /** The status the page opened with (`?status=`). */
  initialStatus?: SearchStatusChoice;
  /** The address of a Reference's detail page. */
  hrefFor: (lineageId: string) => string;
  /** Reads one page of results (the `searchReferences` query). */
  search: ReferenceSearchReader;
  now?: number;
  /** Keep the address in step with the query and the status (a page; off in a fixture). */
  syncAddress?: boolean;
};

type Loaded = { items: ReferenceSearchMatch[]; nextCursor: string | null; lanes: ReferenceSearchPage["lanes"] };

/** Replace `?q=` and `?status=` in the address without a navigation (a server round trip would reload the whole newsroom). */
function writeAddress(query: string, status: SearchStatusChoice) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if (query) params.set("q", query); else params.delete("q");
  if (status !== "any") params.set("status", status); else params.delete("status");
  const text = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${text ? `?${text}` : ""}`);
}

export function NewsroomSearchResults({ initialQuery, initialStatus = "any", hrefFor, search, now, syncAddress = true }: NewsroomSearchResultsProps) {
  const [text, setText] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);
  const [status, setStatus] = useState<SearchStatusChoice>(initialStatus);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const latest = useRef(0);
  const inputId = useId();
  const statusLabelId = useId();
  const clock = now ?? Date.now();

  // The top bar sends a new query by navigating here again: follow it.
  useEffect(() => { setText(initialQuery); setQuery(initialQuery); }, [initialQuery]);
  useEffect(() => { setStatus(initialStatus); }, [initialStatus]);

  useEffect(() => {
    if (!query) { setLoaded(null); setError(null); setLoading(false); return; }
    const mine = ++latest.current;
    setLoading(true);
    setError(null);
    search({ query, show: showForStatus(status), limit: SEARCH_PAGE_SIZE, cursor: null })
      .then((page) => { if (latest.current === mine) { setLoaded(page); setLoading(false); } })
      .catch((failure) => { if (latest.current === mine) { setError(failure instanceof Error ? failure.message : "The search could not be run."); setLoaded(null); setLoading(false); } });
  }, [query, status, retry, search]);

  useEffect(() => { if (syncAddress) writeAddress(query, status); }, [query, status, syncAddress]);

  const submit = useCallback((event: FormEvent) => {
    event.preventDefault();
    const next = normalizeSearchQuery(text);
    setText(next);
    if (next === query) setRetry((value) => value + 1); else setQuery(next);
  }, [query, text]);

  const loadMore = useCallback(async () => {
    if (!loaded?.nextCursor || loadingMore) return;
    const mine = latest.current;
    setLoadingMore(true);
    try {
      const page = await search({ query, show: showForStatus(status), limit: SEARCH_PAGE_SIZE, cursor: loaded.nextCursor });
      if (latest.current === mine) setLoaded((current) => current && ({ items: [...current.items, ...page.items.filter((item) => !current.items.some((held) => held.reference.lineageId === item.reference.lineageId))], nextCursor: page.nextCursor, lanes: page.lanes }));
    } catch (failure) {
      if (latest.current === mine) setError(failure instanceof Error ? failure.message : "More results could not be read.");
    } finally { setLoadingMore(false); }
  }, [loaded, loadingMore, query, search, status]);

  const groups = loaded ? splitSearchResults(loaded.items) : null;
  const notice = loaded ? laneNotice(loaded.lanes) : null;

  return (
    <section aria-labelledby={`${inputId}-title`} className="mx-auto flex w-full max-w-3xl flex-col gap-5 pb-16 pt-2" data-newsroom-search-results>
      <h2 className="text-2xl font-semibold tracking-tight text-foreground" id={`${inputId}-title`}>Search</h2>

      <form className="relative flex items-center" data-search-form onSubmit={submit} role="search">
        <SearchIcon aria-hidden="true" className="pointer-events-none absolute left-4 size-5 text-muted-foreground" />
        <input
          aria-label="Search the References"
          autoComplete="off"
          className="min-h-12 w-full rounded-full bg-[var(--feed-card)] pl-12 pr-28 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          data-search-input
          id={inputId}
          onChange={(event) => setText(event.target.value)}
          placeholder="Search titles, authors and meaning"
          type="search"
          value={text}
        />
        <button className={cn(PILL, "absolute right-1.5 min-h-9 bg-[var(--feed-control)] text-foreground hover:opacity-90")} data-search-submit type="submit">Search</button>
      </form>

      <div className="flex flex-col gap-2" data-search-options>
        <p className="px-1 text-sm font-medium text-muted-foreground" id={statusLabelId}>Show</p>
        <div aria-labelledby={statusLabelId} className="grid grid-cols-2 gap-1.5 rounded-[22px] bg-[var(--feed-card)] p-1.5 sm:flex sm:flex-wrap" data-search-control="status" role="group">
          {SEARCH_STATUS_CHOICES.map((choice) => {
            const Icon = STATUS_ICON[choice];
            return (
              <button
                aria-pressed={status === choice}
                className={cn(PILL, status === choice ? "bg-[var(--feed-control)] font-semibold text-foreground" : "text-muted-foreground hover:text-foreground")}
                data-search-status={choice}
                key={choice}
                onClick={() => setStatus(choice)}
                type="button"
              >
                <Icon aria-hidden="true" className="size-4" />
                {STATUS_LABEL[choice]}
                {status === choice ? <CheckIcon aria-hidden="true" className="size-4" data-search-status-chosen /> : null}
              </button>
            );
          })}
        </div>
      </div>

      {!query ? (
        <p className="rounded-[20px] bg-[var(--feed-card)] p-8 text-center text-base text-muted-foreground" data-search-idle>
          Type a word or a question. Exact words in a title come first; close matches in meaning follow.
        </p>
      ) : null}

      {query && loading && !loaded ? (
        <div aria-busy="true" aria-label="Searching" className="flex flex-col gap-3" data-search-loading role="status">
          {[0, 1, 2].map((index) => <div className="h-28 animate-pulse rounded-[20px] bg-[var(--feed-card)]" key={index} />)}
        </div>
      ) : null}

      {error ? (
        <div className="flex flex-col items-start gap-3 rounded-[20px] bg-[var(--feed-card)] p-5 text-base" data-search-error role="alert">
          <p>{error}</p>
          <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-search-retry onClick={() => setRetry((value) => value + 1)} type="button">
            <RefreshCwIcon aria-hidden="true" className="size-4" /> Try again
          </button>
        </div>
      ) : null}

      {loaded && bothLanesFailed(loaded.lanes) && !error ? (
        <div className="rounded-[20px] bg-[var(--feed-card)] p-5 text-base" data-search-error role="alert">The search could not be run. Try again in a moment.</div>
      ) : null}

      {notice ? <p className="rounded-[16px] bg-[var(--feed-card)] px-4 py-3 text-sm text-foreground" data-search-notice role="status">{notice}</p> : null}

      {query && loaded && groups && !bothLanesFailed(loaded.lanes) ? (
        <div className={cn("flex flex-col gap-8 transition-opacity", loading && "opacity-60")} data-search-results>
          {loaded.items.length === 0 ? (
            <div className="flex flex-col items-start gap-3 rounded-[20px] bg-[var(--feed-card)] p-6 text-base" data-search-empty>
              <p>{status === "any" ? `Nothing matches “${query}”.` : `Nothing matches “${query}” among ${STATUS_LABEL[status].toLowerCase()} References.`}</p>
              {status !== "any" ? <button className={cn(PILL, "bg-[var(--feed-control)] text-foreground")} data-search-status-clear onClick={() => setStatus("any")} type="button">Show any status</button> : null}
            </div>
          ) : null}
          <ResultGroup clock={clock} heading="Title and word matches" hint="Your words are in these." hrefFor={hrefFor} id="word-hits" items={groups.wordHits} />
          <ResultGroup clock={clock} heading="Related" hint="Close in meaning to your search. The words are not in these." hrefFor={hrefFor} id="related" items={groups.related} />
          {loaded.nextCursor ? (
            <button className={cn(PILL, "self-center bg-[var(--feed-control)] px-6 text-foreground")} data-search-more disabled={loadingMore} onClick={() => void loadMore()} type="button">
              {loadingMore ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : null}
              Show more results
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ResultGroup({ clock, heading, hint, hrefFor, id, items }: { clock: number; heading: string; hint: string; hrefFor: (lineageId: string) => string; id: string; items: ReferenceSearchMatch[] }) {
  if (!items.length) return null;
  return (
    <section aria-label={`${heading}, ${items.length}`} className="flex flex-col gap-3" data-search-group={id}>
      <header className="flex flex-col gap-0.5 px-1">
        <h3 className="text-lg font-semibold text-foreground">{heading} <span className="font-normal text-muted-foreground">({items.length})</span></h3>
        <p className="text-sm text-muted-foreground">{hint}</p>
      </header>
      <ol className="flex flex-col gap-3">
        {items.map((match) => {
          const lineage = match.reference.lineageId ?? match.reference.id;
          return <li key={lineage}><ResultCard clock={clock} href={hrefFor(lineage)} match={match} /></li>;
        })}
      </ol>
    </section>
  );
}

function ResultCard({ clock, href, match }: { clock: number; href: string; match: ReferenceSearchMatch }) {
  const reference: ReferenceRecord = match.reference;
  const kind = searchResultKind(match);
  const KindIcon = KIND_ICON[kind];
  const status = searchStatusWord(reference);
  const StatusIcon = status === "Accepted" ? CircleCheckIcon : status === "Rejected" ? CircleXIcon : CircleDashedIcon;
  const host = referenceSourceHost(reference);
  const age = formatFeedAge(referenceDisplayTime(reference), clock);
  const authors = Array.isArray(reference.authors) ? reference.authors.filter(Boolean).slice(0, 3).join(", ") : "";
  return (
    <article className="flex flex-col gap-3 rounded-[20px] bg-[var(--feed-card)] p-4 transition-colors hover:bg-[var(--feed-control)] sm:p-5" data-search-result={reference.lineageId} data-search-kind={kind}>
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-3 py-1 text-foreground" data-search-kind-label>
          <KindIcon aria-hidden="true" className="size-4" /> {SEARCH_KIND_LABEL[kind]}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--feed-footer)] px-3 py-1 text-foreground" data-search-status-label>
          <StatusIcon aria-hidden="true" className="size-4" /> {status}
        </span>
      </div>
      <h4 className="text-lg font-semibold leading-snug text-foreground sm:text-xl">
        <Link className="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring" data-search-open href={href}>{referenceDisplayTitle(reference)}</Link>
      </h4>
      <p className="text-sm leading-relaxed text-muted-foreground" data-search-why>{searchKindExplanation(match)}</p>
      {host || age || authors ? (
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground" data-search-meta>
          {host ? <span>{host}</span> : null}
          {authors ? <span>{authors}</span> : null}
          {age ? <span>{age === "now" ? "just now" : `${age} ago`}</span> : null}
        </p>
      ) : null}
    </article>
  );
}
