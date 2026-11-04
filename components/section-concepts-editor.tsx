"use client";

import { CheckIcon, HashIcon, Loader2Icon, PlusIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { classifyAddInput, conceptSlug, offersCreate, type RelatedItem } from "../lib/reference-links";
import {
  addTrackedConcept, fallbackConceptName, removeTrackedConcept, setTrackedConceptNote, type TrackedConcept,
} from "../lib/section-concepts";
import { cn } from "@/lib/utils";
import { useReferenceLinksStore } from "./reference-links-context";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";

const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";
const TILE = "rounded-2xl !border-0 bg-muted text-foreground";
const BUTTON = "inline-flex items-center gap-1.5 rounded-2xl !border-0 bg-muted px-3 py-1.5 text-sm font-medium normal-case tracking-normal text-foreground shadow-none outline-none hover:bg-muted/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-60";

/**
 * "Concepts this section tracks": the concepts every agent working in the section should be especially aware of. The same typed # box as the Related
 * section on a Reference (type # and a name; pick a match, or press "Create #name"), then a row for each concept with its optional note and a Remove button.
 * The list is changed in the caller's draft; the section's own Save writes it.
 */
export function SectionConceptsEditor({ actor = "editor", disabled = false, entries, names = {}, onChange }: {
  actor?: string;
  disabled?: boolean;
  entries: TrackedConcept[];
  names?: Record<string, string>;
  onChange: (next: TrackedConcept[]) => void;
}) {
  const store = useReferenceLinksStore();
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  const [results, setResults] = useState<RelatedItem[]>([]);
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ticket = useRef(0);
  const parsed = classifyAddInput(text);
  const nameOf = (lineageId: string) => picked[lineageId] ?? names[lineageId] ?? fallbackConceptName(lineageId);
  useEffect(() => {
    const mine = ++ticket.current;
    if (!store || parsed.mode !== "concept") { setResults([]); setSearched(false); return; }
    store.searchConcepts(parsed.query).then(found => {
      if (mine !== ticket.current) return;
      setResults(found.slice(0, 8));
      setSearched(true);
    }).catch(() => { if (mine === ticket.current) { setResults([]); setSearched(true); } });
  }, [store, parsed.mode, parsed.query]);
  if (!store) return null;
  const track = (item: RelatedItem) => {
    setPicked(current => ({ ...current, [item.lineageId]: item.hashtag ?? item.title }));
    onChange(addTrackedConcept(entries, item.lineageId, actor, new Date().toISOString()));
    setText("");
    setResults([]);
    setSearched(false);
    setProblem(null);
  };
  const creatable = store.createConcept && parsed.mode === "concept" ? offersCreate(parsed.query, results) : null;
  const create = async () => {
    if (!creatable || busy || !store.createConcept) return;
    setBusy(true);
    setProblem(null);
    try {
      track(await store.createConcept(creatable));
    } catch {
      setProblem("The concept could not be created.");
    } finally {
      setBusy(false);
    }
  };
  const onEnter = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || disabled || busy || parsed.mode !== "concept") return;
    event.preventDefault();
    const exact = results.find(item => conceptSlug(item.hashtag ?? "") === conceptSlug(parsed.query));
    if (exact) track(exact);
    else void create();
  };
  return (
    <section className={cn(TILE, "grid gap-y-3 bg-muted/40 p-3")} data-section-concepts>
      <h4 className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><HashIcon aria-hidden="true" className="size-4" />Concepts this section tracks</h4>
      <p className="text-xs text-muted-foreground">Every agent working in this section is told about these concepts, with the note you write here.</p>
      {entries.length ? (
        <div className="grid gap-y-2" data-section-concepts-list>
          {entries.map(entry => (
            <div className="grid gap-y-1.5 rounded-2xl bg-background/60 p-2" data-section-concept={entry.conceptLineageId} key={entry.conceptLineageId}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground"><HashIcon aria-hidden="true" className="size-3.5" />{nameOf(entry.conceptLineageId)}</span>
                <button className={BUTTON} data-section-concept-remove={entry.conceptLineageId} disabled={disabled} onClick={() => onChange(removeTrackedConcept(entries, entry.conceptLineageId))} type="button">
                  <XIcon aria-hidden="true" className="size-4" />Remove
                </button>
              </div>
              <AutoGrowTextarea
                aria-label={`Note on ${nameOf(entry.conceptLineageId)}`}
                className={cn(TILE, "!min-h-9 w-full !border-0 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring")}
                disabled={disabled}
                onChange={event => onChange(setTrackedConceptNote(entries, entry.conceptLineageId, event.target.value))}
                placeholder="Optional: why this concept matters in this section"
                rows={1}
                value={entry.note ?? ""}
              />
            </div>
          ))}
        </div>
      ) : <p className="text-xs text-muted-foreground" data-section-concepts-empty>This section tracks no concepts yet.</p>}
      <div className="grid gap-y-1.5" data-section-concepts-add>
        <span className={cn(LABEL, "text-muted-foreground")}>Add a concept</span>
        <AutoGrowTextarea
          aria-label="Add a concept this section tracks"
          className={cn(TILE, "!min-h-9 w-full !border-0 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring")}
          disabled={disabled}
          onChange={event => { setText(event.target.value); setProblem(null); }}
          onKeyDown={onEnter}
          placeholder="Type # and a concept name"
          rows={1}
          value={text}
        />
        {results.map(item => (
          <button
            className={cn(TILE, "flex w-full min-w-0 items-center gap-1.5 px-3 py-2 text-left text-sm font-semibold text-foreground outline-none hover:bg-muted/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-60")}
            data-section-concepts-result={item.lineageId}
            disabled={disabled || busy || entries.some(entry => entry.conceptLineageId === item.lineageId)}
            key={item.lineageId}
            onClick={() => track(item)}
            type="button"
          >
            <HashIcon aria-hidden="true" className="size-3.5" />{item.hashtag}
            <span className="font-normal text-muted-foreground">{item.title}{item.nodeKind ? ` · ${item.nodeKind.replace(/_/g, " ")}` : ""}</span>
            {entries.some(entry => entry.conceptLineageId === item.lineageId) ? <span className="ml-auto inline-flex items-center gap-1 text-xs font-normal"><CheckIcon aria-hidden="true" className="size-3.5" />Tracked</span> : null}
          </button>
        ))}
        {creatable ? (
          <button className={cn(TILE, "flex w-full min-w-0 items-center gap-1.5 px-3 py-2 text-left text-sm font-semibold text-foreground outline-none hover:bg-muted/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-60")} data-section-concepts-create={creatable} disabled={disabled || busy} onClick={() => void create()} type="button">
            {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <PlusIcon aria-hidden="true" className="size-4" />}
            <span className="min-w-0 break-words">Create #{creatable}</span>
          </button>
        ) : null}
        {searched && !results.length && !creatable ? <p className="text-xs text-muted-foreground">No concept matches that hashtag.</p> : null}
        {problem ? <span className="text-xs text-destructive" role="alert">{problem}</span> : null}
      </div>
    </section>
  );
}
