"use client";

import { useState } from "react";
import { primingStateText, type PrimingRequestView } from "../lib/relevance-status";

export type PrimingFormInput = { url: string; label: string; explanation: string };

/**
 * A compact form that primes the running relevance cyclotron with a pasted
 * URL. The next sweep reads the page, adds it to the cyclotron's example list
 * and records the outcome, which this list shows beside each saved request.
 */
export function ReferenceCyclotronPriming({
  labels,
  requests,
  onRequestPriming,
}: {
  labels: readonly string[];
  requests: PrimingRequestView[];
  onRequestPriming: (input: PrimingFormInput) => Promise<void> | void;
}) {
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState(labels[0] ?? "");
  const [explanation, setExplanation] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function submit() {
    setMessage("Saving…");
    try {
      await onRequestPriming({ url, label, explanation });
      setUrl("");
      setExplanation("");
      setMessage("Saved. The next sweep reads the page and adds it to the cyclotron.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section aria-label="Prime the relevance cyclotron" className="space-y-2 text-sm" data-reference-cyclotron-priming>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="flex min-w-64 flex-1 flex-col gap-1">
          <span className="text-xs text-muted-foreground">Prime with a URL</span>
          <input
            aria-label="Priming URL"
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://"
            required
            type="url"
            value={url}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Label</span>
          <select aria-label="Priming label" onChange={(event) => setLabel(event.target.value)} value={label}>
            {labels.map((choice) => (
              <option key={choice} value={choice}>{choice}</option>
            ))}
          </select>
        </label>
        <label className="flex min-w-48 flex-1 flex-col gap-1">
          <span className="text-xs text-muted-foreground">Why (optional)</span>
          <input aria-label="Priming explanation" onChange={(event) => setExplanation(event.target.value)} type="text" value={explanation} />
        </label>
        <button className="cyclotron-review-secondary" type="submit">Save</button>
        {message ? <p className="basis-full text-xs" role="status">{message}</p> : null}
      </form>
      {requests.length ? (
        <ul aria-label="Saved priming requests" className="space-y-1 text-xs text-muted-foreground">
          {requests.slice(0, 10).map((view) => (
            <li data-priming-request-state={view.outcome?.state ?? "waiting"} key={view.request.requestId}>
              <span className="font-medium">{view.request.label}</span> {view.request.url} · {primingStateText(view)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
