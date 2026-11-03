"use client";

import { CheckIcon, HashIcon, LinkIcon, Loader2Icon, SparklesIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { openSuggestions, suggestionLoaderFor } from "../lib/card-suggestions";
import { classifyAddInput, closeMatchText, type RelatedEntry } from "../lib/reference-links";
import { cn } from "@/lib/utils";
import { CreateConceptAction } from "./related-section";
import { useReferenceLinksStore } from "./reference-links-context";
import { AutoGrowTextarea } from "./ui/auto-grow-textarea";

const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";

/**
 * The few most likely suggested concepts and related References on the card an editor curates, each with Accept and Reject in one tap: the same decision as
 * the Related section (`ReferenceLinksStore.decide`), recorded the same way. Curating, rating and tagging happen in one pass.
 *
 * Suggestions are read only once the card is on screen, through a loader shared by the feed that reads a few References at a time, and a card with none shows
 * nothing at all. `action` is for anything else a surface wants beside them; the hashtag box (`CreateConceptAction`) is built in.
 */
/**
 * A small box on the card: type `#name` and one button creates the concept if it is new and tags the Reference with it (`CreateConceptAction`, the same action
 * as the Related section's add box). No dialog; it appears only where the store can create concepts.
 */
function CardHashtagBox({ disabled, lineageId }: { disabled: boolean; lineageId: string }) {
  const store = useReferenceLinksStore();
  const [text, setText] = useState("");
  const [done, setDone] = useState<string | null>(null);
  if (!store?.createConceptAndTag) return null;
  const parsed = classifyAddInput(text);
  return (
    <div className="grid gap-y-1.5" data-card-hashtag>
      <AutoGrowTextarea
        aria-label="Tag with a hashtag"
        className="min-h-9 w-full rounded-[var(--feed-radius-md,16px)] border-0 bg-[var(--feed-control)] px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring"
        disabled={disabled}
        onChange={(event) => { setText(event.target.value); setDone(null); }}
        placeholder="Tag it: type # and a name"
        rows={1}
        value={text}
      />
      {parsed.mode === "concept" && parsed.query ? (
        <CreateConceptAction disabled={disabled} name={parsed.query} onDone={(item) => { setText(""); setDone(item.hashtag ?? item.title); }} referenceLineageId={lineageId} />
      ) : null}
      {done ? <span className="inline-flex items-center gap-1 text-xs text-foreground" data-card-hashtag-done role="status"><CheckIcon aria-hidden="true" className="size-3.5" />Tagged {done}</span> : null}
    </div>
  );
}

export function CardSuggestions({ action, disabled = false, inset = "", lineageId }: { action?: ReactNode; disabled?: boolean; /** Classes (the footer's tone and padding) applied only while there is something to show, so a card without suggestions keeps its height. */ inset?: string; lineageId: string }) {
  const store = useReferenceLinksStore();
  const root = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [entries, setEntries] = useState<RelatedEntry[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const node = root.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") { setVisible(true); return; }
    const observer = new IntersectionObserver((seen) => { if (seen.some((entry) => entry.isIntersecting)) { setVisible(true); observer.disconnect(); } }, { rootMargin: "200px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!store || !visible) return;
    let active = true;
    suggestionLoaderFor(store).load(lineageId).then((found) => { if (active) setEntries(found); }).catch(() => { if (active) setEntries([]); });
    return () => { active = false; };
  }, [store, visible, lineageId]);

  const decide = useCallback(async (entry: RelatedEntry, decision: "accept" | "reject") => {
    if (!store) return;
    setBusy(entry.relationId);
    setError(null);
    try {
      await store.decide({ relationId: entry.relationId, decision });
      setEntries((current) => (current ?? []).filter((row) => row.relationId !== entry.relationId));
      suggestionLoaderFor(store).forget(lineageId);
    } catch {
      setError("The decision could not be saved. Try again.");
    } finally {
      setBusy(null);
    }
  }, [lineageId, store]);

  if (!store) return null;
  const { concepts, references } = openSuggestions(entries ?? []);
  const shown = [...concepts, ...references];
  return (
    <div className={cn("grid gap-y-1.5", shown.length || action || store.createConceptAndTag ? inset : "")} data-card-suggestions={lineageId} ref={root}>
      {shown.length ? (
        <>
          <span className={cn(LABEL, "inline-flex items-center gap-1 text-muted-foreground")}><SparklesIcon aria-hidden="true" className="size-3" />Suggested links</span>
          <ul className="grid gap-y-1.5">
            {shown.map((entry) => {
              const concept = entry.item.kind === "concept";
              const match = closeMatchText(entry.similarity);
              return (
                <li className="grid gap-y-1.5 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-card)] p-2" data-card-suggestion={entry.relationId} data-card-suggestion-kind={concept ? "concept" : "reference"} key={entry.relationId}>
                  <span className="flex min-w-0 items-center gap-x-1.5 px-1 text-sm leading-5">
                    {concept ? <HashIcon aria-hidden="true" className="size-3.5 shrink-0" /> : <LinkIcon aria-hidden="true" className="size-3.5 shrink-0" />}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-foreground" data-card-suggestion-title>{concept ? entry.item.hashtag ?? entry.item.title : entry.item.title}</span>
                      {match ? <span className="block truncate text-xs text-muted-foreground">{match}</span> : null}
                    </span>
                    {busy === entry.relationId ? <Loader2Icon aria-hidden="true" className="size-4 shrink-0 animate-spin" /> : null}
                  </span>
                  <span className="grid grid-cols-2 gap-x-1.5">
                    <button aria-label={`Accept ${concept ? "concept" : "link"} ${entry.item.title}`} className="inline-flex min-h-10 items-center justify-center gap-1 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)] px-3 text-sm font-medium text-foreground outline-none hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]" data-card-suggestion-accept disabled={disabled || busy !== null} onClick={() => void decide(entry, "accept")} type="button"><CheckIcon aria-hidden="true" className="size-4" />Accept</button>
                    <button aria-label={`Reject ${concept ? "concept" : "link"} ${entry.item.title}`} className="inline-flex min-h-10 items-center justify-center gap-1 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]/45 px-3 text-sm font-medium text-muted-foreground outline-none hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-[var(--feed-quiet,0.6)]" data-card-suggestion-reject disabled={disabled || busy !== null} onClick={() => void decide(entry, "reject")} type="button"><XIcon aria-hidden="true" className="size-4" />Reject</button>
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
      {action ? <div data-card-suggestions-action>{action}</div> : null}
      <CardHashtagBox disabled={disabled} lineageId={lineageId} />
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
    </div>
  );
}
