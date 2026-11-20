"use client";

import { CheckIcon, HashIcon, LinkIcon, Loader2Icon, PencilIcon, PlusIcon, QuoteIcon, SparklesIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  classifyAddInput, closeMatchText, conceptSlug, EDITOR_CONCEPT_KIND, explanationByline, offersCreate, publishedAddedText, relatedEdgeWords, suggestFailureText, suggestSkippedText,
  type RelatedEntry, type RelatedItem, type SuggestionLabel,
} from "../lib/reference-links";
import { cn } from "@/lib/utils";
import { DecisionControl, type RatingFeedback } from "./decision-control";
import type { ReviewChoice } from "./reference-review-card";
import { useReferenceLinksStore, type ReferenceLinksStore } from "./reference-links-context";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";

const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";
const TILE = "rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]";

/** Always the plain fallback: a backend or network message is internal wording and is never shown to an editor. */
function failureText(_failure: unknown, fallback: string): string {
  return fallback;
}

/** References whose suggestions were asked for on opening, in this page's life: asked once, not on every visit to the panel. */
const triedAutomatically = new Set<string>();

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

export function ReferenceCard({ edge, explanation, href, item, suggestion }: { edge?: string; explanation?: ReactNode; href?: string | null; item: RelatedItem; suggestion?: ReactNode }) {
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
      {explanation}
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

const EXPLANATION_BUTTON = "inline-flex items-center gap-1.5 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)] px-2.5 py-1 text-xs font-semibold text-foreground outline-none hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]";
const EXPLANATION_BLOCK = "grid w-full gap-y-1.5 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-card)] p-2";

/**
 * The words an editor wrote when they accepted or made a link, shown on that link with who wrote them. An editor adds or changes them in place; a
 * viewer without editor access reads them. The words are meaning, not decoration: the idea writer reads them too (PPY-89c85a). `editing` is held by
 * the caller so it can give a link with words, or one being edited, a row of its own.
 */
function LinkExplanation({ editable, editing, entry, onEditingChange, onSave }: {
  editable: boolean;
  editing: boolean;
  entry: RelatedEntry;
  onEditingChange: (editing: boolean) => void;
  onSave: (entry: RelatedEntry, text: string) => Promise<void>;
}) {
  const explanation = entry.explanation ?? null;
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = () => { setDraft(explanation?.text ?? ""); setError(null); onEditingChange(true); };
  const close = () => { setError(null); onEditingChange(false); };
  const save = async () => {
    const text = draft.trim();
    if (text === (explanation?.text ?? "")) { close(); return; }
    setSaving(true);
    setError(null);
    try {
      await onSave(entry, text);
      onEditingChange(false);
    } catch (failure) {
      setError(failureText(failure, "The explanation could not be saved."));
    } finally {
      setSaving(false);
    }
  };
  if (editing && editable) {
    return (
      <div className={EXPLANATION_BLOCK} data-related-explanation={entry.relationId} data-related-explanation-editing>
        <span className={cn(LABEL, "inline-flex items-center gap-1 text-muted-foreground")}><QuoteIcon aria-hidden="true" className="size-3.5" />Explanation</span>
        <AutoGrowTextarea
          aria-label="Explain why these are linked"
          autoFocus
          className={cn(TILE, "min-h-9 w-full border-0 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring")}
          data-related-explanation-input
          disabled={saving}
          onChange={event => setDraft(event.target.value)}
          placeholder="Why are these linked? Say it in your own words."
          rows={2}
          value={draft}
        />
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <button className={EXPLANATION_BUTTON} data-related-explanation-save disabled={saving} onClick={() => void save()} type="button">
            {saving ? <Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" /> : <CheckIcon aria-hidden="true" className="size-3.5" />}Save
          </button>
          <button className={EXPLANATION_BUTTON} data-related-explanation-cancel disabled={saving} onClick={close} type="button"><XIcon aria-hidden="true" className="size-3.5" />Cancel</button>
          {error ? <span className="text-xs text-destructive" role="alert">{error}</span> : null}
        </div>
      </div>
    );
  }
  if (!explanation) {
    return editable ? (
      <button className={EXPLANATION_BUTTON} data-related-explanation-add={entry.relationId} onClick={open} type="button"><PlusIcon aria-hidden="true" className="size-3.5" />Add explanation</button>
    ) : null;
  }
  return (
    <div className={EXPLANATION_BLOCK} data-related-explanation={entry.relationId}>
      <span className={cn(LABEL, "inline-flex items-center gap-1 text-muted-foreground")}><QuoteIcon aria-hidden="true" className="size-3.5" />Explanation</span>
      <p className="whitespace-pre-wrap break-words text-sm leading-5 text-foreground" data-related-explanation-text>{explanation.text}</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span data-related-explanation-byline>{explanationByline(explanation)}</span>
        {editable ? <button className={EXPLANATION_BUTTON} data-related-explanation-edit={entry.relationId} onClick={open} type="button"><PencilIcon aria-hidden="true" className="size-3.5" />Edit</button> : null}
      </div>
    </div>
  );
}

type SaveExplanation = (entry: RelatedEntry, text: string) => Promise<void>;

function ConceptEntry({ editable, entry, onSave }: { editable: boolean; entry: RelatedEntry; onSave: SaveExplanation }) {
  const [editing, setEditing] = useState(false);
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", entry.explanation || editing ? "w-full" : "")} data-related-concept-entry={entry.relationId}>
      <ConceptChip item={entry.item} />
      <LinkExplanation editable={editable} editing={editing} entry={entry} onEditingChange={setEditing} onSave={onSave} />
    </div>
  );
}

function ExplainedReferenceCard({ editable, edge, entry, href, onSave }: { editable: boolean; edge?: string; entry: RelatedEntry; href?: string | null; onSave: SaveExplanation }) {
  const [editing, setEditing] = useState(false);
  return (
    <ReferenceCard
      edge={edge}
      explanation={<LinkExplanation editable={editable} editing={editing} entry={entry} onEditingChange={setEditing} onSave={onSave} />}
      href={href}
      item={entry.item}
    />
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

/**
 * "Create #name and tag this": one button, no dialog and no fields. It asks the store to invent the concept if it does not exist and to tag the Reference
 * with it. Pressing it twice makes one concept and one link (the busy state stops the second tap and the backend makes the same node for the same name).
 * Reusable from a card: give it the Reference's lineage id and the typed name.
 */
export function CreateConceptAction({ disabled = false, name, onDone, referenceLineageId }: { disabled?: boolean; name: string; onDone?: (item: RelatedItem) => void | Promise<void>; referenceLineageId: string }) {
  const store = useReferenceLinksStore();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const slug = conceptSlug(name);
  if (!store?.createConceptAndTag || !slug) return null;
  const create = async () => {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const made = await store.createConceptAndTag!(referenceLineageId, slug);
      await onDone?.(made.item);
    } catch (problem) {
      setFailure(failureText(problem, "The concept could not be created."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        className={cn(TILE, "flex w-full min-w-0 items-center gap-1.5 px-3 py-2 text-left text-sm font-semibold text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]")}
        data-related-create={slug}
        disabled={disabled || busy}
        onClick={() => void create()}
        type="button"
      >
        {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <PlusIcon aria-hidden="true" className="size-4" />}
        <span className="min-w-0 break-words">Create #{slug} and tag this</span>
      </button>
      {failure ? <span className="text-xs text-destructive" role="alert">{failure}</span> : null}
    </>
  );
}

function AddLinkBox({ disabled, mode, onCreated, onPick, referenceLineageId, search }: {
  disabled: boolean;
  mode: "reference-side" | "concept-side";
  onCreated?: (item: RelatedItem) => Promise<void>;
  onPick: (item: RelatedItem) => Promise<void>;
  referenceLineageId?: string;
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
      setMessage({ kind: "error", text: failureText(failure, "The search did not work. Try again.") });
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
  const creatable = conceptsAllowed && parsed.mode === "concept" && referenceLineageId && onCreated ? offersCreate(parsed.query, results) : null;
  const created = async (item: RelatedItem) => {
    await onCreated?.(item);
    setText("");
    setResults([]);
    setSearched(false);
    setMessage({ kind: "done", text: `Created and tagged ${item.hashtag ?? item.title}` });
  };
  // Enter takes the exact match if there is one, else creates the concept: one key, no dialog.
  const onEnter = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || disabled || busy || parsed.mode !== "concept") return;
    event.preventDefault();
    const exact = results.find(item => item.kind === "concept" && conceptSlug(item.hashtag ?? "") === conceptSlug(parsed.query));
    if (exact) void pick(exact);
    else if (creatable) document.querySelector<HTMLButtonElement>(`[data-related-create="${creatable}"]`)?.click();
  };
  const placeholder = conceptsAllowed ? "Type # for a concept, or paste a link or a title" : "Paste a link or a title";
  return (
    <div className="grid gap-y-1.5" data-related-add>
      <AutoGrowTextarea
        aria-label="Add a related link"
        className={cn(TILE, "min-h-9 w-full border-0 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring")}
        disabled={disabled}
        onChange={event => { setText(event.target.value); setMessage(null); }}
        onKeyDown={onEnter}
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
      {creatable ? <CreateConceptAction disabled={disabled || busy} name={creatable} onDone={created} referenceLineageId={referenceLineageId as string} /> : null}
      {searched && !results.length && !creatable ? <p className="text-xs text-muted-foreground" data-related-no-results>{parsed.mode === "concept" ? "No concept matches that hashtag." : "No Reference matches that."}</p> : null}
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
  const suggestMore = async () => {
    if (!store) return;
    setSuggesting(true);
    setSuggestNote(null);
    try {
      const outcome = await store.suggest(referenceId ?? lineageId);
      setLabels(current => ({ ...current, ...outcome.labels }));
      if (outcome.skipped) setSuggestNote(suggestSkippedText(outcome.skipped));
      void reload();   // the spinner stops now; the new rows appear when the list has been read again
    } catch (failure) {
      setSuggestNote(suggestFailureText(failure));
    } finally {
      setSuggesting(false);
    }
  };
  // A Reference that is opened with no links and has not been tried gets its suggestions once, without a click (a failure or a skip is said in the same note).
  const suggestKey = `${referenceId ?? lineageId}`;
  useEffect(() => {
    if (!store || disabled || state !== "ready" || entries.length || triedAutomatically.has(suggestKey)) return;
    triedAutomatically.add(suggestKey);
    void suggestMore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, disabled, state, entries.length, suggestKey]);
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
  const explain: SaveExplanation = async (entry, text) => {
    await store.decide({ relationId: entry.relationId, decision: "accept", note: text });
    await reload();
  };
  const addLink = async (item: RelatedItem) => {
    await store.create({ subjectLineageId: lineageId, objectKind: item.kind === "concept" ? "semanticNode" : "reference", objectLineageId: item.lineageId, predicate: item.kind === "concept" ? "tagged_with" : "related_to" });
    await reload();
  };
  const renderReference = (entry: RelatedEntry) => entry.state === "suggested" ? (
    <ReferenceCard
      edge={relatedEdgeWords(entry.predicate, entry.direction)}
      href={hrefForReference?.(entry.item.lineageId) ?? null}
      item={entry.item}
      key={entry.relationId}
      suggestion={<><SuggestionMarks entry={entry} /><SuggestedDecision disabled={disabled} entry={entry} onDecide={decide} /></>}
    />
  ) : (
    <ExplainedReferenceCard edge={relatedEdgeWords(entry.predicate, entry.direction)} editable={!disabled} entry={entry} href={hrefForReference?.(entry.item.lineageId) ?? null} key={entry.relationId} onSave={explain} />
  );
  return (
    <section className={cn(TILE, "grid gap-y-3 bg-[var(--feed-footer,var(--feed-control))] p-3")} data-related-section={lineageId}>
      <SectionHeader>Related</SectionHeader>
      {state === "loading" ? <p className="text-xs text-muted-foreground">Loading links…</p> : null}
      {state === "error" ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
      <div className="grid gap-y-2" data-related-concepts>
        <span className={cn(LABEL, "text-muted-foreground")}>Concepts</span>
        {confirmedConcepts.length ? <div className="flex flex-wrap gap-1.5">{confirmedConcepts.map(entry => <ConceptEntry editable={!disabled} entry={entry} key={entry.relationId} onSave={explain} />)}</div> : state === "ready" ? <p className="text-xs text-muted-foreground">No concepts linked yet.</p> : null}
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
      <AddLinkBox disabled={disabled} mode="reference-side" onCreated={async () => { await reload(); }} onPick={addLink} referenceLineageId={lineageId} search={{ concepts: store.searchConcepts, references: store.searchReferences }} />
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

/**
 * On the page of a concept an editor invented: its description, written in place. No dialog: "Add a description" opens a text box, Save keeps the words (empty
 * clears them). Other concepts are generated by the knowledge runs and are not edited here. A viewer without editor access reads the words only.
 */
export function ConceptDescription({ description, disabled = false, lineageId, nodeKind }: { description?: string | null; disabled?: boolean; lineageId: string; nodeKind: string }) {
  const store = useReferenceLinksStore();
  const [saved, setSaved] = useState(description ?? "");
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const editable = Boolean(store?.describeConcept) && nodeKind === EDITOR_CONCEPT_KIND && !disabled;
  const save = async () => {
    if (draft === null || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await store!.describeConcept!(lineageId, draft.trim());
      setSaved(draft.trim());
      setDraft(null);
    } catch {
      setFailure("The description could not be saved.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-y-1.5" data-concept-description>
      {draft === null ? (
        <>
          {saved ? saved.split(/\n{2,}/).map((paragraph, index) => <p key={index}>{paragraph}</p>) : <p className="wiki-empty">This concept has no description yet.</p>}
          {editable ? (
            <button
              className={cn(TILE, "inline-flex w-fit items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-foreground outline-none hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring")}
              data-concept-description-edit
              onClick={() => setDraft(saved)}
              type="button"
            >
              <PencilIcon aria-hidden="true" className="size-4" />{saved ? "Edit description" : "Add a description"}
            </button>
          ) : null}
        </>
      ) : (
        <>
          <AutoGrowTextarea
            aria-label="Describe this concept"
            className={cn(TILE, "min-h-20 w-full border-0 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring")}
            data-concept-description-input
            onChange={event => setDraft(event.target.value)}
            placeholder="What this concept means, in a sentence or two"
            rows={3}
            value={draft}
          />
          <div className="flex gap-2">
            <button className={cn(TILE, "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]")} data-concept-description-save disabled={busy} onClick={() => void save()} type="button">
              {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <CheckIcon aria-hidden="true" className="size-4" />}Save
            </button>
            <button className={cn(TILE, "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring")} disabled={busy} onClick={() => { setDraft(null); setFailure(null); }} type="button">
              <XIcon aria-hidden="true" className="size-4" />Cancel
            </button>
          </div>
        </>
      )}
      {failure ? <span className="text-xs text-destructive" role="alert">{failure}</span> : null}
    </div>
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
    await store.create({ subjectLineageId: item.lineageId, objectKind: "semanticNode", objectLineageId: conceptLineageId, predicate: "tagged_with" });
    await reload();
  };
  const explain: SaveExplanation = async (entry, text) => {
    await store.decide({ relationId: entry.relationId, decision: "accept", note: text });
    await reload();
  };
  return (
    <section className="grid gap-y-2" data-wiki-section="linked-by-editors">
      <h2>Linked by editors</h2>
      {state === "loading" ? <p className="wiki-empty">Loading links…</p> : null}
      {state === "error" ? <p className="wiki-empty" role="alert">{error}</p> : null}
      {state === "ready" && !entries.length ? <p className="wiki-empty">No References linked by editors yet.</p> : null}
      <div className="grid gap-y-2" data-linked-by-editors-list>
        {entries.map(entry => <ExplainedReferenceCard editable={!disabledReason} entry={entry} href={hrefForReference?.(entry.item.lineageId) ?? null} key={entry.relationId} onSave={explain} />)}
      </div>
      <AddLinkBox disabled={Boolean(disabledReason)} mode="concept-side" onPick={addLink} search={{ concepts: store.searchConcepts, references: store.searchReferences }} />
      {disabledReason ? <p className="text-xs text-muted-foreground">{disabledReason}</p> : null}
    </section>
  );
}
