"use client";

import { useState } from "react";
import { CheckIcon, StarIcon } from "lucide-react";
import {
  ADD_REFERENCE_STAR_CHOICES,
  addedMessage,
  type AddReferenceInput,
  type AddReferenceOutcome,
} from "../lib/add-reference";

/**
 * The "Paste a URL" option of the Add a reference area. The address becomes a real, pending Reference at once. An editor who added it
 * because it is good can accept it and rate it from 1 to 5 stars on the spot; both are optional and are the editor's own decision.
 * Buttons only, flat tones, and every state is a mark plus words, never colour alone.
 */
export function ReferenceAddUrl({ onAdd }: { onAdd: (input: AddReferenceInput) => Promise<AddReferenceOutcome> }) {
  const [url, setUrl] = useState("");
  const [accept, setAccept] = useState(false);
  const [stars, setStars] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<{ text: string; problems: string[] } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setFailure(null);
    setMessage(null);
    try {
      const outcome = await onAdd({ url, accept, stars, note });
      setMessage({ text: addedMessage(outcome), problems: outcome.problems });
      setUrl("");
      setAccept(false);
      setStars(null);
      setNote("");
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 text-sm" data-reference-add-url>
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
            className="rounded-xl bg-[var(--feed-control)] px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://"
            required
            type="url"
            value={url}
          />
        </label>

        <div className="flex flex-col gap-2" role="group" aria-label="Your decision (optional)">
          <span className="text-xs text-muted-foreground">Your decision (optional)</span>
          <div className="flex flex-wrap items-center gap-2">
            <button
              aria-pressed={accept}
              className={`inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-base font-semibold ${accept ? "bg-foreground text-background" : "bg-[var(--feed-control)] text-foreground"}`}
              data-add-accept
              onClick={() => setAccept((on) => !on)}
              type="button"
            >
              <CheckIcon aria-hidden="true" className="size-4" strokeWidth={accept ? 3 : 1.5} />
              {accept ? "Accepted" : "Accept"}
            </button>
            <div aria-label="Star rating" className="inline-flex items-center gap-1" role="group">
              {ADD_REFERENCE_STAR_CHOICES.map((value) => {
                const filled = stars !== null && value <= stars;
                return (
                  <button
                    aria-label={`${value} ${value === 1 ? "star" : "stars"}`}
                    aria-pressed={stars === value}
                    className={`inline-flex size-11 items-center justify-center rounded-full ${filled ? "bg-[var(--feed-control)]" : ""}`}
                    data-add-star={value}
                    key={value}
                    onClick={() => {
                      // A star lights itself and every star to its left; the top star again clears. A rating is also an acceptance, so Accept follows it.
                      setStars((current) => (current === value ? null : value));
                      if (stars !== value) setAccept(true);
                    }}
                    title={stars === value ? "Tap again to clear the rating" : `${value} of 5 stars`}
                    type="button"
                  >
                    <StarIcon aria-hidden="true" className="size-5" fill={filled ? "currentColor" : "none"} strokeWidth={filled ? 1.5 : 2} />
                  </button>
                );
              })}
            </div>
            <span className="text-xs text-muted-foreground" data-add-star-summary>{stars === null ? "Not rated" : `${stars} of 5 stars`}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            Adding without a decision leaves the reference pending for review. Accepting and rating are your own decisions and teach Papyrus what you want.
          </p>
        </div>

        {accept ? (
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">Why?</span>
            <textarea
              aria-label="Reason"
              className="w-full rounded-xl bg-[var(--feed-control)] px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onChange={(event) => setNote(event.target.value)}
              placeholder="A sentence or two helps Papyrus learn what you want."
              rows={3}
              value={note}
            />
            <span className="text-xs text-muted-foreground">Optional.</span>
          </label>
        ) : null}

        <div>
          <button className="cyclotron-review-secondary" disabled={busy} type="submit">{busy ? "Adding…" : "Add reference"}</button>
        </div>
        {failure ? <p className="text-xs" role="alert">Not added. {failure}</p> : null}
        {message ? (
          <div className="space-y-1 text-xs" role="status">
            <p>{message.text}</p>
            {message.problems.map((problem) => <p key={problem}>Needs attention: {problem}</p>)}
          </div>
        ) : null}
      </form>
    </div>
  );
}
