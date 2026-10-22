"use client";

import { useId, useRef, useState, type KeyboardEvent } from "react";
import { primingStateText, type PrimingRequestView } from "../lib/relevance-status";

export type PrimingFormInput = { url: string; label: string; explanation: string };

/**
 * The "Paste a URL" option of the Add a reference area. The page is read in the
 * background and the outcome is shown beside each added reference.
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

  const ratingLabelId = useId();
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);

  function moveSelection(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
    const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";
    if (!forward && !backward) return;
    event.preventDefault();
    const next = (index + (forward ? 1 : -1) + labels.length) % labels.length;
    setLabel(labels[next]);
    buttons.current[next]?.focus();
  }

  async function submit() {
    setMessage("Adding…");
    try {
      await onRequestPriming({ url, label, explanation });
      setUrl("");
      setExplanation("");
      setMessage("Added. The page will be read shortly.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="space-y-2 text-sm" data-reference-cyclotron-priming>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Web page address</span>
          <input
            aria-label="Reference URL"
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://"
            required
            type="url"
            value={url}
          />
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground" id={ratingLabelId}>Should Papyrus include or exclude pages like this?</span>
          <div aria-labelledby={ratingLabelId} className="flex flex-wrap gap-2" role="radiogroup">
            {labels.map((choice, index) => {
              const checked = choice === label;
              return (
                <button
                  aria-checked={checked}
                  className={`min-w-32 flex-1 rounded border px-4 py-3 text-base font-semibold capitalize ${checked ? "border-foreground bg-foreground text-background" : "border-border bg-transparent"}`}
                  data-rating-choice={choice}
                  key={choice}
                  onClick={() => setLabel(choice)}
                  onKeyDown={(event) => moveSelection(event, index)}
                  ref={(node) => { buttons.current[index] = node; }}
                  role="radio"
                  tabIndex={checked || (!labels.includes(label) && index === 0) ? 0 : -1}
                  type="button"
                >
                  {choice}
                </button>
              );
            })}
          </div>
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Why?</span>
          <textarea
            aria-label="Reason"
            className="w-full"
            onChange={(event) => setExplanation(event.target.value)}
            placeholder="Why? A sentence or two helps Papyrus learn what you want."
            rows={4}
            value={explanation}
          />
          <span className="text-xs text-muted-foreground">Optional, but a short reason helps Papyrus learn what you want.</span>
        </label>
        <div>
          <button className="cyclotron-review-secondary" type="submit">Add reference</button>
        </div>
        {message ? <p className="text-xs" role="status">{message}</p> : null}
      </form>
      {requests.length ? (
        <ul aria-label="Added references" className="space-y-1 text-xs text-muted-foreground">
          {requests.slice(0, 10).map((view) => (
            <li data-priming-request-state={view.outcome?.state ?? "waiting"} key={view.request.requestId}>
              <span className="font-medium">{view.request.label}</span> {view.request.url} · {primingStateText(view)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
