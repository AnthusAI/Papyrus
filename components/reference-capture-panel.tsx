"use client";

import { FileCheckIcon, FileWarningIcon, FileXIcon, Loader2Icon } from "lucide-react";
import { useState } from "react";
import { captureLine, type CaptureState, type CaptureStatus } from "../lib/reference-capture";
import { cn } from "@/lib/utils";
import type { CaptureView } from "./reference-capture-client";

const ICON = { full: FileCheckIcon, thin: FileWarningIcon, none: FileXIcon } as const;
/** Colour never stands alone: each state has its own icon and words. */
const TONE: Record<CaptureState, string> = {
  full: "bg-emerald-600/15 text-emerald-900 dark:bg-emerald-400/15 dark:text-emerald-100",
  thin: "bg-amber-500/20 text-amber-900 dark:bg-amber-300/15 dark:text-amber-100",
  none: "bg-red-600/15 text-red-900 dark:bg-red-400/15 dark:text-red-100",
};

/** A small badge for a grid card, so a thin or missing capture shows before the item is opened. */
export function CaptureBadge({ status }: { status: CaptureStatus }) {
  const Icon = ICON[status.state];
  const text = status.state === "none" ? "No text" : status.state === "thin" ? (status.words === null ? "Little text" : `${status.words.toLocaleString("en-US")} words`) : "Full text";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-medium", TONE[status.state])} data-capture-badge={status.state} title={captureLine(status).label}>
      <Icon aria-hidden="true" className="size-3.5" />
      {text}
    </span>
  );
}

const PREVIEW_CHARACTERS = 1600;

/** Our captured record of a Reference: what we stored of its content, said plainly, above the live source preview. */
export function ReferenceCapturePanel({ capture }: { capture: CaptureView }) {
  const [expanded, setExpanded] = useState(false);
  const line = captureLine(capture.status);
  const Icon = ICON[line.state];
  const text = capture.text ?? "";
  const long = text.length > PREVIEW_CHARACTERS;
  return (
    <section aria-label="Our captured record" className="space-y-3" data-capture-panel={line.state}>
      <h3 className="text-sm font-semibold text-foreground">Our captured record</h3>
      <div className={cn("flex items-start gap-3 rounded-2xl p-3", TONE[line.state])} data-capture-status={line.state}>
        <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-semibold" data-capture-label>{line.label}</p>
          {line.state === "full" ? null : <p className="text-xs opacity-90" data-capture-detail>{line.detail}</p>}
          {capture.status.words !== null ? <p className="text-xs font-medium" data-capture-words>{capture.status.estimated ? "about " : ""}{capture.status.words.toLocaleString("en-US")} words</p> : null}
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
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Summary</h4>
          <p className="text-sm">{capture.summary}</p>
        </div>
      ) : null}
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
    </section>
  );
}
