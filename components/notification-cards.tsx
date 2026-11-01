"use client";

import { CircleCheckIcon, CircleXIcon } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { RecentDecision } from "../lib/notification-feed";
import { FEED_SURFACE_PROPS } from "./reference-feed";

export type DecidedChoice = "accept" | "reject";

const CARD = "flex flex-col overflow-hidden rounded-[20px] bg-[var(--feed-card)] text-card-foreground";

/** Pulsing placeholder cards in the shape of the real ones, on screen the moment the page opens. */
export function NotificationSkeleton({ bare = false, count = 3 }: { bare?: boolean; count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading what needs you" className="space-y-6" data-notification-skeleton role="status" {...FEED_SURFACE_PROPS}>
      {bare ? null : (
        <>
          <div className="space-y-3">
            <div className="h-8 w-2/3 max-w-md animate-pulse rounded-full bg-[var(--feed-control)]" />
            <div className="h-4 w-1/3 max-w-xs animate-pulse rounded-full bg-[var(--feed-control)]" />
          </div>
          <div className="h-11 animate-pulse rounded-[20px] bg-[var(--feed-card)]" />
          <div className="flex gap-2">
            {[0, 1, 2, 3, 4].map((index) => <div className="h-9 w-24 animate-pulse rounded-full bg-[var(--feed-control)]" key={index} />)}
          </div>
        </>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(17rem,1fr))] gap-5">
        {Array.from({ length: count }, (_, index) => (
          <div className={CARD} key={index}>
            <div className="aspect-[16/10] animate-pulse bg-[var(--feed-control)]" />
            <div className="space-y-3 p-5">
              <div className="h-3 w-1/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="h-5 w-11/12 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="h-5 w-2/3 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="h-3 w-1/2 animate-pulse rounded-full bg-[var(--feed-control)]" />
            </div>
            <div className="flex gap-2 bg-[var(--feed-footer)] p-3">
              <div className="h-12 flex-1 animate-pulse rounded-[16px] bg-[var(--feed-control)]" />
              <div className="h-12 flex-1 animate-pulse rounded-[16px] bg-[var(--feed-control)]" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DecidedLine({ choice, notThisKind, why }: { choice: DecidedChoice; notThisKind?: boolean; why?: string | null }) {
  const Icon = choice === "accept" ? CircleCheckIcon : CircleXIcon;
  return (
    <p className="flex items-start gap-1.5 text-sm font-medium" data-draft-decided={choice}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="break-words">
        {choice === "accept" ? "Accepted" : "Rejected"}{choice === "reject" && notThisKind ? " as not this kind" : ""}
        {why ? <span className="font-normal text-muted-foreground">: {why}</span> : null}
      </span>
    </p>
  );
}

/** The last few things the editor decided, as slim rows: what, when, and where to look again. */
export function RecentDecisions({ entries }: { entries: RecentDecision[] }) {
  if (!entries.length) return null;
  return (
    <ul aria-label="Recently decided" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" data-recent-decisions {...FEED_SURFACE_PROPS}>
      {entries.map((entry) => {
        const Icon = entry.choice === "reject" ? CircleXIcon : CircleCheckIcon;
        const body = (
          <>
            <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span className="min-w-0">
              <span className="block break-words text-sm font-medium leading-snug">{entry.title}</span>
              <span className="block text-xs text-muted-foreground">
                {entry.word}{entry.at ? ` · ${new Date(entry.at).toISOString().slice(0, 10)}` : ""}{entry.note ? ` · ${entry.note}` : ""}
              </span>
            </span>
          </>
        );
        return (
          <li data-recent-decision={entry.key} key={entry.key}>
            {entry.href ? (
              <Link className="flex items-start gap-2 rounded-[16px] bg-[var(--feed-card)] p-3 outline-none hover:bg-[var(--feed-control)] focus-visible:ring-2 focus-visible:ring-ring" href={entry.href}>{body}</Link>
            ) : <div className="flex items-start gap-2 rounded-[16px] bg-[var(--feed-card)] p-3">{body}</div>}
          </li>
        );
      })}
    </ul>
  );
}
