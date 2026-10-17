"use client";

import { useState } from "react";
import { CyclotronStatusView } from "cyclotron/components/cyclotron-status";
import type { CyclotronStatus } from "cyclotron/cyclotron-status";

const RATE_CHOICES = [1, 0.5, 0.25, 0.1, 0];
const DAY_CHOICES = [1, 7, 14, 30];

export type ReviewRateChoice = { rate: number; days: number } | { clear: true };

/**
 * The relevance cyclotron's status above the References list: a strip, the
 * detail card on demand, and, for editors who may change it, a form that asks
 * the next sweep for a manual review rate.
 */
export function ReferenceCyclotronStatus({
  onRequestRate,
  status,
  staleAfterHours = 24,
  now = new Date(),
}: {
  onRequestRate?: (choice: ReviewRateChoice) => Promise<void> | void;
  status: CyclotronStatus;
  staleAfterHours?: number;
  now?: Date;
}) {
  const [open, setOpen] = useState(false);
  const [rate, setRate] = useState(0.5);
  const [days, setDays] = useState(7);
  const [message, setMessage] = useState<string | null>(null);
  const ageHours = Math.max(0, (now.getTime() - Date.parse(status.asOf)) / 3_600_000);
  const stale = Number.isFinite(ageHours) && ageHours > staleAfterHours;
  const override = status.reviewRate.override;

  async function submit(choice: ReviewRateChoice) {
    if (!onRequestRate) return;
    setMessage("Sending…");
    try {
      await onRequestRate(choice);
      setMessage("The next sweep applies it and the status will show who set it.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section aria-label="Relevance cyclotron" className="space-y-2" data-reference-cyclotron-status>
      <CyclotronStatusView status={status} />
      {stale ? (
        <p className="text-xs text-muted-foreground" data-reference-cyclotron-status-stale>
          <span aria-hidden="true">⚠ </span>
          Snapshot from {Math.round(ageHours)} hours ago; the next sweep refreshes it.
        </p>
      ) : null}
      <button
        aria-expanded={open}
        className="text-xs text-muted-foreground underline underline-offset-4"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        {open ? "Hide what the cyclotron is doing" : "What the cyclotron is doing"}
      </button>
      {open ? (
        <div className="space-y-3">
          <CyclotronStatusView classifierName="Relevant to this publication" status={status} variant="card" />
          {onRequestRate ? (
            <form
              aria-label="Manual review rate"
              className="flex flex-wrap items-end gap-3 text-sm"
              data-reference-review-rate-form
              onSubmit={(event) => {
                event.preventDefault();
                void submit({ rate, days });
              }}
            >
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Review rate for confident decisions</span>
                <select aria-label="Manual review rate" onChange={(event) => setRate(Number(event.target.value))} value={rate}>
                  {RATE_CHOICES.map((choice) => (
                    <option key={choice} value={choice}>{Math.round(choice * 100)}%</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">For</span>
                <select aria-label="How long the manual rate lasts" onChange={(event) => setDays(Number(event.target.value))} value={days}>
                  {DAY_CHOICES.map((choice) => (
                    <option key={choice} value={choice}>{choice} day{choice === 1 ? "" : "s"}</option>
                  ))}
                </select>
              </label>
              <button className="cyclotron-review-secondary" type="submit">Set manual rate</button>
              {override ? (
                <button className="cyclotron-review-secondary" onClick={() => void submit({ clear: true })} type="button">
                  Clear manual rate
                </button>
              ) : null}
              <p className="basis-full text-xs text-muted-foreground">
                Low-confidence decisions and the random audit share are always reviewed.
              </p>
              {message ? <p className="basis-full text-xs" role="status">{message}</p> : null}
            </form>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
