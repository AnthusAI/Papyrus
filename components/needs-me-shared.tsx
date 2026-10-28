"use client";

import { CheckIcon, CircleCheckIcon, Loader2Icon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import type { ReviewChoice } from "./reference-review-card";

/** References and captures are rated like the References feed: a reason code is asked for on Reject. */
export function isReferenceLike(item: Pick<NeedsMeEntry, "type">): boolean {
  return item.type === "reference" || item.type === "incomplete_capture";
}

export function decidedChoiceOf(item: Pick<NeedsMeEntry, "decisionState">): ReviewChoice | null {
  return item.decisionState === "accepted" ? "accept" : item.decisionState === "rejected" ? "reject" : null;
}

/** A flag is information, not a question: one Acknowledge button in the footer's own tone. */
export function FlagFooter({ busy, disabledReason, done, error, onAcknowledge }: { busy: boolean; disabledReason: string | null; done: boolean; error: string | null; onAcknowledge: () => void }) {
  return (
    <div className="space-y-2" data-flag-footer>
      {done ? (
        <p className="inline-flex min-h-12 items-center gap-1.5 text-sm font-medium" data-flag-acknowledged><CircleCheckIcon aria-hidden="true" className="size-4" />Acknowledged</p>
      ) : (
        <button
          aria-disabled={busy || Boolean(disabledReason) || undefined}
          className={cn("inline-flex min-h-12 w-full items-center justify-center gap-1.5 rounded-[16px] bg-[var(--feed-control)] px-3 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-2 focus-visible:ring-ring", (busy || disabledReason) && "opacity-60")}
          data-flag-acknowledge
          onClick={() => { if (!busy && !disabledReason) onAcknowledge(); }}
          type="button"
        >
          {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <CheckIcon aria-hidden="true" className="size-4" />}
          {busy ? "Saving…" : "Acknowledge"}
        </button>
      )}
      {disabledReason && !done ? <p className="text-xs text-muted-foreground" data-review-disabled-reason>{disabledReason}</p> : null}
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
    </div>
  );
}
