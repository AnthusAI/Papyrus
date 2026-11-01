"use client";

import { CheckIcon, HashIcon, LinkIcon, Loader2Icon, SparklesIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  KNOWLEDGE_INDEX_MISSING_TEXT, classifyAddInput, closeMatchText, isKnowledgeIndexMissing, publishedAddedText, relatedEdgeWords,
  type RelatedEntry, type RelatedItem, type SuggestionLabel,
} from "../lib/reference-links";
import { cn } from "@/lib/utils";
import { DecisionControl, type RatingFeedback } from "./decision-control";
import type { ReviewChoice } from "./reference-review-card";
import { useReferenceLinksStore, type ReferenceLinksStore } from "./reference-links-context";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";

const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";
const TILE = "rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]";

function failureText(failure: unknown, fallback: string): string {
  return failure instanceof Error && failure.message ? failure.message : fallback;
}

function useEntries(load: (() => Promise<RelatedEntry[]>) | null) {
  const [entries, setEntries] = useState<RelatedEntry[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const enabled = Boolean(load);
  const reload = useCallback(async () => {
    const current = loadRef.current;
    if (!current) return;
    try {
      setEntries(await current());
      setState("ready");
      setError(null);
    } catch (failure) {
      setError(failureText(failure, "The links could not be loaded."));
      setState("error");
    }
  }, []);
  useEffect(() => { if (enabled) void reload(); }, [enabled, reload]);
  return { entries, state, error, reload };
}

function DatesLine({ item }: { item: RelatedItem }) {
  return <span className="text-xs text-muted-foreground" data-related-dates>{publishedAddedText(item.sourcePublishedAt, item.addedAt)}</span>;
}

export function ReferenceCard({ edge, href, item, suggestion }: { edge?: string; href?: string | null; item: RelatedItem; suggestion?: ReactNode }) {
  return (
    <div className={cn(suggestion ? "rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-card)]" : TILE, "grid gap-y-1 px-3 py-2")} data-related-reference-card={item.lineageId}>
      <span className="text-sm font-semibold leading-5 text-foreground" data-related-title>
        {href ? <a className="underline-offset-2 hover:underline" href={href}>{item.title}</a> : item.title}
      </span>
      <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        {item.host ? <span data-related-host>{item.host}</span> : null}
        {edge ? <span data-related-edge>{edge}</span> : null}
      </span>
      <DatesLine item={item} />
      {suggestion}
    </div>
  );
}

function ConceptChip({ item }: { item: RelatedItem }) {
  return (
    <span className={cn(TILE, "inline-flex items-center gap-1.5 px-2.5 py-1 text-sm font-medium text-foreground")} data-related-concept={item.lineageId}>
      <HashIcon aria-hidden="true" className="size-3.5" />
      <span data-related-hashtag>{item.hashtag ?? item.title}</span>
    </span>
  );
}

function SuggestionMarks({ entry }: { entry: RelatedEntry }) {
  const match = closeMatchText(entry.similarity);
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground" data-related-suggestion-marks>
      <span className="inline-flex items-center gap-1 font-semibold text-foreground"><SparklesIcon aria-hidden="true" className="size-3.5" />Suggested</span>
      {match ? <span data-related-close-match>{match}</span> : null}
      {entry.label ? <span data-related-likelihood>{entry.label}</span> : null}
    </span>
  );
}

function SuggestedDecision({ disabled, entry, onDecide }: { disabled: boolean; entry: RelatedEntry; onDecide: (entry: RelatedEntry, choice: ReviewChoice, reason: string) => Promise<void> }) {
  const [answer, setAnswer] = useState<ReviewChoice | null>(null);
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState<RatingFeedback>({ phase: "idle" });
  const choose = async (choice: ReviewChoice) => {
    setAnswer(choice);
    setFeedback({ phase: "saving" });
    try {
      await onDecide(entry, choice, reason.trim());
      setFeedback({ phase: "saved" });
    } catch (failure) {
      setAnswer(null);
      setFeedback({ phase: "error", message: failureText(failure, "The decision could not be saved.") });
    }
  };
  return (
    <div data-related-decision={entry.relationId}>
      <DecisionControl
        answer={answer}
        decided={feedback.phase === "saved" ? answer : null}
        disabled={disabled}
        feedback={feedback}
        onChoose={choose}
        onReasonChange={setReason}
        prediction={{ state: "none" }}
        reason={reason}
        showPrediction={false}
        surface="card"
      />
    </div>
  );
}

function AddLinkBox({ disabled, mode, onPick, search }: {
  disabled: boolean;
  mode: "reference-side" | "concept-side";
  onPick: (item: RelatedItem) => Promise<void>;
  search: { concepts: ReferenceLinksStore["searchConcepts"]; references: ReferenceLinksStore["searchReferences"] };
}) {
  const [text, setText] = useState("");
  const [results, setResults] = useState<RelatedItem[]>([]);
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "done" | "error"; text: string } | null>(null);
  const ticket = useRef(0);
  const searchRef = useRef(search);
  searchRef.current = search;
  const parsed = classifyAddInput(text);
  const conceptsAllowed = mode === "reference-side";
  useEffect(() => {
    const mine = ++ticket.current;
    if (parsed.mode === "none" || (parsed.mode === "concept" && !conceptsAllowed)) {
      setResults([]);
      setSearched(false);
      return;
    }
    const run = parsed.mode === "concept" ? searchRef.current.concepts(parsed.query) : searchRef.current.references(parsed.query);
    run.then(found => {
      if (mine !== ticket.current) return;
      setResults(found.slice(0, 8));
      setSearched(true);
    }).catch(failure => {
      if (mine !== ticket.current) return;
      setResults([]);
      setSearched(true);
      setMessage({ kind: "error", text: failureText(failure, "The search failed.") });
    });
  }, [conceptsAllowed, parsed.mode, parsed.query]);
  const pick = async (item: RelatedItem) => {
    setBusy(true);
    setMessage(null);
    try {
      await onPick(item);
      setText("");
      setResults([]);
      setSearched(false);
      setMessage({ kind: "done", text: `Linked ${item.hashtag ?? item.title}` });
    } catch (failure) {
      setMessage({ kind: "error", text: failureText(failure, "The link could not be saved.") });
    } finally {
      setBusy(false);
    }
  };
  const placeholder = conceptsAllowed ? "Type # for a concept, or paste a link or a title" : "Paste a link or a title";
  return (
    <div className="grid gap-y-1.5" data-related-add>
      <AutoGrowTextarea
        aria-label="Add a related link"
        className={cn(TILE, "min-h-9 w-full border-0 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring")}
        disabled={disabled}
        onChange={event => { setText(event.target.value); setMessage(null); }}
        placeholder={placeholder}
        rows={1}
        value={text}
      />
      {results.map(item => (
        <button
          className={cn(TILE, "flex w-full min-w-0 flex-col items-start gap-y-0.5 px-3 py-2 text-left outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]")}
          data-related-result={item.lineageId}
          disabled={disabled || busy}
          key={`${item.kind}-${item.lineageId}`}
          onClick={() => void pick(item)}
          type="button"
        >
          {item.kind === "concept" ? (
            <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <HashIcon aria-hidden="true" className="size-3.5" />{item.hashtag}
              <span className="font-normal text-muted-foreground">{item.title}{item.nodeKind ? ` · ${item.nodeKind.replace(/_/g, " ")}` : ""}</span>
            </span>
          ) : (
            <>
              <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground"><LinkIcon aria-hidden="true" className="size-3.5" />{item.title}</span>
              <span className="text-xs text-muted-foreground">{item.host ? `${item.host} · ` : ""}{publishedAddedText(item.sourcePublishedAt, item.addedAt)}</span>
            </>
          )}
        </button>
      ))}
      {searched && !results.length ? <p className="text-xs text-muted-foreground" data-related-no-results>{parsed.mode === "concept" ? "No concept matches that hashtag." : "No Reference matches that."}</p> : null}
      <div className="min-h-5 text-xs text-muted-foreground" role="status">
        {busy ? <span className="inline-flex items-center gap-1"><Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Linking…</span> : null}
        {message?.kind === "done" ? <span className="inline-flex items-center gap-1 text-foreground" data-related-linked><CheckIcon aria-hidden="true" className="size-3.5" />{message.text}</span> : null}
        {message?.kind === "error" ? <span className="text-destructive" role="alert">{message.text}</span> : null}
      </div>
    </div>
  );
}

function SectionHeader({ children }: { children: ReactNode }) {
  return <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><LinkIcon aria-hidden="true" className="size-4" />{children}</h3>;
}

/** Related concepts and References on one Reference: confirmed links, suggestions to decide, and a box to add one. */
export function RelatedSection({ disabledReason = null, hrefForReference, lineageId, referenceId }: {
  disabledReason?: string | null;
  hrefForReference?: (lineageId: string) => string | null;
  lineageId: string;
  referenceId?: string;
}) {
  const store = useReferenceLinksStore();
  const { entries, state, error, reload } = useEntries(store ? () => store.listForReference(lineageId) : null);
  const [labels, setLabels] = useState<Record<string, SuggestionLabel>>({});
  const [suggesting, setSuggesting] = useState(false);
  const [suggestNote, setSuggestNote] = useState<string | null>(null);
  const disabled = Boolean(disabledReason);
  if (!store) return null;
  const labelled = entries.map(entry => (entry.state === "suggested" && labels[entry.item.lineageId] ? { ...entry, label: labels[entry.item.lineageId] } : entry));
  const concepts = labelled.filter(entry => entry.item.kind === "concept");
  const references = labelled.filter(entry => entry.item.kind === "reference");
  const confirmedConcepts = concepts.filter(entry => entry.state === "current");
  const suggestedConcepts = concepts.filter(entry => entry.state === "suggested");
  const decide = async (entry: RelatedEntry, choice: ReviewChoice, reason: string) => {
    await store.decide({ relationId: entry.relationId, decision: choice, ...(reason ? { note: reason } : {}) });
    await reload();
  };
  const suggestMore = async () => {
    setSuggesting(true);
    setSuggestNote(null);
    try {
      const outcome = await store.suggest(referenceId ?? lineageId);
      setLabels(current => ({ ...current, ...outcome.labels }));
      if (outcome.skipped) setSuggestNote(outcome.skipped);
      await reload();
    } catch (failure) {
      setSuggestNote(isKnowledgeIndexMissing(failure) ? KNOWLEDGE_INDEX_MISSING_TEXT : failureText(failure, "Suggestions could not be made."));
    } finally {
      setSuggesting(false);
    }
  };
  const addLink = async (item: RelatedItem) => {
    await store.create({ subjectLineageId: lineageId, objectKind: item.kind === "concept" ? "semanticNode" : "reference", objectLineageId: item.lineageId, predicate: "related_to" });
    await reload();
  };
  const renderReference = (entry: RelatedEntry) => (
    <ReferenceCard
      edge={relatedEdgeWords(entry.predicate, entry.direction)}
      href={hrefForReference?.(entry.item.lineageId) ?? null}
      item={entry.item}
      key={entry.relationId}
      suggestion={entry.state === "suggested" ? <><SuggestionMarks entry={entry} /><SuggestedDecision disabled={disabled} entry={entry} onDecide={decide} /></> : undefined}
    />
  );
  return (
    <section className={cn(TILE, "grid gap-y-3 bg-[var(--feed-footer,var(--feed-control))] p-3")} data-related-section={lineageId}>
      <SectionHeader>Related</SectionHeader>
      {state === "loading" ? <p className="text-xs text-muted-foreground">Loading links…</p> : null}
      {state === "error" ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
      <div className="grid gap-y-2" data-related-concepts>
        <span className={cn(LABEL, "text-muted-foreground")}>Concepts</span>
        {confirmedConcepts.length ? <div className="flex flex-wrap gap-1.5">{confirmedConcepts.map(entry => <ConceptChip item={entry.item} key={entry.relationId} />)}</div> : state === "ready" ? <p className="text-xs text-muted-foreground">No concepts linked yet.</p> : null}
        {suggestedConcepts.map(entry => (
          <div className="grid gap-y-1.5 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-card)] p-2" data-related-suggested={entry.relationId} key={entry.relationId}>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><ConceptChip item={entry.item} /><SuggestionMarks entry={entry} /></div>
            <SuggestedDecision disabled={disabled} entry={entry} onDecide={decide} />
          </div>
        ))}
      </div>
      <div className="grid gap-y-2" data-related-references>
        <span className={cn(LABEL, "text-muted-foreground")}>References</span>
        {references.length ? references.map(renderReference) : state === "ready" ? <p className="text-xs text-muted-foreground">No References linked yet.</p> : null}
      </div>
      <AddLinkBox disabled={disabled} mode="reference-side" onPick={addLink} search={{ concepts: store.searchConcepts, references: store.searchReferences }} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          className={cn(TILE, "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-foreground outline-none hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]")}
          data-related-suggest-more
          disabled={disabled || suggesting}
          onClick={() => void suggestMore()}
          type="button"
        >
          {suggesting ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <SparklesIcon aria-hidden="true" className="size-4" />}
          Suggest more
        </button>
        {suggestNote ? <span className="text-xs text-muted-foreground" data-related-suggest-note role="status">{suggestNote}</span> : null}
      </div>
      {disabledReason ? <p className="text-xs text-muted-foreground">{disabledReason}</p> : null}
    </section>
  );
}

/** On a concept page: the References editors linked to it, each with both dates, and the same box to link another one. */
export function LinkedByEditors({ conceptLineageId, disabledReason = null, hrefForReference }: {
  conceptLineageId: string;
  disabledReason?: string | null;
  hrefForReference?: (lineageId: string) => string | null;
}) {
  const store = useReferenceLinksStore();
  const { entries, state, error, reload } = useEntries(store ? () => store.listLinkedByEditors(conceptLineageId) : null);
  if (!store) return null;
  const addLink = async (item: RelatedItem) => {
    await store.create({ subjectLineageId: item.lineageId, objectKind: "semanticNode", objectLineageId: conceptLineageId, predicate: "related_to" });
    await reload();
  };
  return (
    <section className="grid gap-y-2" data-wiki-section="linked-by-editors">
      <h2>Linked by editors</h2>
      {state === "loading" ? <p className="wiki-empty">Loading links…</p> : null}
      {state === "error" ? <p className="wiki-empty" role="alert">{error}</p> : null}
      {state === "ready" && !entries.length ? <p className="wiki-empty">No References linked by editors yet.</p> : null}
      <div className="grid gap-y-2" data-linked-by-editors-list>
        {entries.map(entry => <ReferenceCard href={hrefForReference?.(entry.item.lineageId) ?? null} item={entry.item} key={entry.relationId} />)}
      </div>
      <AddLinkBox disabled={Boolean(disabledReason)} mode="concept-side" onPick={addLink} search={{ concepts: store.searchConcepts, references: store.searchReferences }} />
      {disabledReason ? <p className="text-xs text-muted-foreground">{disabledReason}</p> : null}
    </section>
  );
}
