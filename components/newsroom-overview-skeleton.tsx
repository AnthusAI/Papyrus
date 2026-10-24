"use client";

import * as React from "react";

/** Placeholder geometry for the overview while private records or access are unresolved. */
export function NewsroomOverviewSkeleton() {
  return (
    <div aria-label="Loading newsroom overview" className="space-y-8 font-sans" data-newsroom-overview-skeleton role="status">
      <section className="newsroom-overview-feed-frame space-y-4 overflow-hidden rounded-xl border bg-card p-4" aria-label="Notification Center">
        <div className="h-6 w-48 rounded bg-muted" />
        <div className="h-4 w-3/4 max-w-xl rounded bg-muted" />
        <div className="h-4 w-2/3 max-w-lg rounded bg-muted" />
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }, (_, index) => <div className="h-28 rounded-xl border bg-card p-4" key={index}>
            <div className="h-4 w-2/3 rounded bg-muted" /><div className="mt-4 h-3 w-1/2 rounded bg-muted" />
          </div>)}
        </div>
      </section>
      <section aria-label="Needs attention" className="space-y-3">
        <div className="h-4 w-32 rounded bg-muted" />
        <div className="h-16 rounded-xl border bg-card p-4"><div className="h-4 w-1/2 rounded bg-muted" /><div className="mt-2 h-3 w-1/3 rounded bg-muted" /></div>
      </section>
    </div>
  );
}
