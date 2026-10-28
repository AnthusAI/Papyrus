"use client";

import { FileCheckIcon, FileClockIcon, FileWarningIcon, FileXIcon, Loader2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { captureLine, type CaptureAssessment, type CaptureState, type CaptureStatus } from "../lib/reference-capture";
import { cn } from "@/lib/utils";
import type { CaptureView } from "./reference-capture-client";

const ICON = { full: FileCheckIcon, thin: FileWarningIcon, none: FileXIcon, running: FileClockIcon } as const;
/** Colour never stands alone: each state has its own icon and words. */
const TONE: Record<CaptureState, string> = {
  full: "bg-emerald-600/15 text-emerald-900 dark:bg-emerald-400/15 dark:text-emerald-100",
  thin: "bg-amber-500/20 text-amber-900 dark:bg-amber-300/15 dark:text-amber-100",
  none: "bg-red-600/15 text-red-900 dark:bg-red-400/15 dark:text-red-100",
  running: "bg-[var(--feed-control)] text-foreground",
};

/** A small badge for a grid card, so a thin or missing capture shows before the item is opened. It follows the curation status when there is one. */
export function CaptureBadge({ status }: { status: CaptureStatus }) {
  const Icon = ICON[status.state];
  const text = status.state === "none" ? "No text" : status.state === "running" ? "Capturing" : status.state === "thin" ? (status.words === null || status.thinBy === "signals" ? "Maybe cut off" : `${status.words.toLocaleString("en-US")} words`) : "Full text";
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-medium", TONE[status.state])}
      data-capture-badge={status.state}
      data-capture-curation={status.curation ?? undefined}
      data-capture-source={status.source}
      title={captureLine(status).label}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {text}
    </span>
  );
}

const PREVIEW_CHARACTERS = 1600;
const ASSESSMENTS: Array<{ key: CaptureAssessment; label: string; hint: string }> = [
  { key: "complete", label: "Complete", hint: "This is the whole item." },
  { key: "incomplete", label: "Incomplete", hint: "Something is missing or cut off." },
  { key: "incorrect", label: "Incorrect", hint: "This is not the right text." },
];

/** "Paste or correct the text": an editor's own text and verdict on the capture, saved with `correctReferenceCapture`. */
function CorrectionForm({ capture, onDone }: { capture: CaptureView; onDone: () => void }) {
  const [text, setText] = useState(capture.text ?? "");
  const [assessment, setAssessment] = useState<CaptureAssessment | null>(null);
  const [note, setNote] = useState("");
  const [phase, setPhase] = useState<"idle" | "saving" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => { setText((current) => current || capture.text || ""); }, [capture.text]);
  const changedText = text.trim() !== (capture.text ?? "").trim() && text.trim().length > 0;
  const reason = !assessment ? "Say whether the capture was complete, incomplete or incorrect to save." : null;
  async function save() {
    if (!assessment || !capture.correct) return;
    setPhase("saving");
    setMessage(null);
    try {
      await capture.correct({ ...(changedText ? { text: text.trim() } : {}), assessment, ...(note.trim() ? { note: note.trim() } : {}) });
      onDone();
    } catch (failure) {
      setPhase("error");
      setMessage(failure instanceof Error ? failure.message : "The correction could not be saved.");
    }
  }
  return (
    <div className="space-y-3 rounded-2xl bg-[var(--feed-control)] p-3" data-capture-correction>
      <label className="block text-sm font-medium">
        The text
        <textarea
          aria-label="Captured text"
          className="mt-1 block min-h-40 w-full rounded-2xl bg-[var(--feed-card)] p-3 text-sm font-normal"
          data-capture-correction-text
          onChange={(event) => setText(event.target.value)}
          placeholder="Paste the whole article here, or fix what was captured."
          value={text}
        />
      </label>
      <div aria-label="Was the capture complete?" className="flex flex-wrap gap-2" role="group">
        {ASSESSMENTS.map((option) => (
          <button
            aria-pressed={assessment === option.key}
            className={cn("inline-flex min-h-9 items-center rounded-full px-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring", assessment === option.key ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--feed-card)]")}
            data-capture-assessment={option.key}
            key={option.key}
            onClick={() => setAssessment(option.key)}
            title={option.hint}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>
      <label className="block text-sm font-medium">
        Note (optional)
        <textarea aria-label="Note about the capture (optional)" className="mt-1 block min-h-16 w-full rounded-2xl bg-[var(--feed-card)] p-3 text-sm font-normal" onChange={(event) => setNote(event.target.value)} value={note} />
      </label>
      {reason ? <p className="text-xs text-muted-foreground" data-capture-correction-reason>{reason}</p> : null}
      {phase === "error" ? <p className="text-xs text-destructive" role="alert">{message}</p> : null}
      <div className="flex gap-2">
        <button
          aria-disabled={reason ? true : undefined}
          className={cn("inline-flex min-h-9 items-center gap-1.5 rounded-full bg-[var(--primary)] px-4 text-sm font-semibold text-[var(--primary-foreground)] outline-none focus-visible:ring-2 focus-visible:ring-ring", reason && "opacity-60")}
          data-capture-correction-save
          onClick={() => { if (!reason && phase !== "saving") void save(); }}
          type="button"
        >
          {phase === "saving" ? <><Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Saving…</> : changedText ? "Save the text and my verdict" : "Save my verdict"}
        </button>
        <button className="inline-flex min-h-9 items-center rounded-full bg-[var(--feed-card)] px-4 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={onDone} type="button">Cancel</button>
      </div>
    </div>
  );
}

/** Our captured record of a Reference: what we stored of its content, said plainly, above the live source preview. */
export function ReferenceCapturePanel({ capture, startEditing = false }: { capture: CaptureView; startEditing?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(startEditing && Boolean(capture.correct));
  const [savedNote, setSavedNote] = useState(false);
  const line = captureLine(capture.status);
  const Icon = ICON[line.state];
  const text = capture.text ?? "";
  const long = text.length > PREVIEW_CHARACTERS;
  return (
    <section aria-label="Our captured record" className="space-y-3" data-capture-panel={line.state}>
      <h3 className="text-sm font-semibold text-foreground">Our captured record</h3>
      <div className={cn("flex items-start gap-3 rounded-2xl p-3", TONE[line.state])} data-capture-status={line.state} data-capture-source={capture.status.source}>
        <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-semibold" data-capture-label>{line.label}</p>
          {line.state === "full" ? null : <p className="text-xs opacity-90" data-capture-detail>{line.detail}</p>}
          {capture.status.words !== null ? <p className="text-xs font-medium" data-capture-words>{capture.status.estimated ? "about " : ""}{capture.status.words.toLocaleString("en-US")} words</p> : null}
          {line.state === "full" && capture.status.flags?.length ? <p className="text-xs opacity-90" data-capture-flags>{capture.status.flags.join(" ")}</p> : null}
          {capture.status.curation === "degraded" ? <p className="text-xs opacity-90" data-capture-curation-note>Curation finished all but one stage (usually the summary).</p> : null}
          {capture.status.assessment ? <p className="text-xs font-medium" data-capture-assessment-note>An editor marked this capture {capture.status.assessment}.</p> : null}
        </div>
      </div>
      {capture.loading ? <p className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status"><Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />Reading the stored text…</p> : null}
      {capture.error ? <p className="text-xs text-destructive" role="alert">The stored text could not be read. {capture.error}</p> : null}
      {text ? (
        <div className="space-y-2">
          <div className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-2xl bg-[var(--feed-control)] p-3 text-sm leading-relaxed" data-capture-text tabIndex={0}>
            {expanded || !long ? text : `${text.slice(0, PREVIEW_CHARACTERS)}…`}
          </div>
          {long ? (
            <button className="rounded-full bg-[var(--feed-control)] px-3 py-1.5 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring" data-capture-toggle onClick={() => setExpanded((value) => !value)} type="button">
              {expanded ? "Show less" : "Show all of the captured text"}
            </button>
          ) : null}
        </div>
      ) : null}
      {capture.summary ? (
        <div className="space-y-1" data-capture-summary>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Summary{capture.summaryStale ? " (out of date: the text was replaced)" : ""}</h4>
          <p className="text-sm">{capture.summary}</p>
        </div>
      ) : capture.summaryStale ? <p className="text-xs text-muted-foreground" data-capture-summary-stale>The summary will be rewritten from the new text on the next curation run.</p> : null}
      {capture.rows.length ? (
        <dl className="grid gap-2 rounded-2xl bg-[var(--feed-control)] p-3 text-sm" data-capture-structured>
          {capture.rows.map((row) => (
            <div key={`${row.label}:${row.value}`}>
              <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{row.label}</dt>
              <dd className="mt-0.5">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {capture.correct ? (
        editing ? <CorrectionForm capture={capture} onDone={() => { setEditing(false); setSavedNote(true); }} /> : (
          <div className="flex flex-wrap items-center gap-2">
            <button className="inline-flex min-h-9 items-center rounded-full bg-[var(--feed-control)] px-4 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring" data-capture-correct onClick={() => { setSavedNote(false); setEditing(true); }} type="button">
              Paste or correct the text
            </button>
            {savedNote ? <span className="text-xs text-muted-foreground" data-capture-correction-saved role="status">Saved. Your verdict trains the completeness check.</span> : null}
          </div>
        )
      ) : null}
    </section>
  );
}
