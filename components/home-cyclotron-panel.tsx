"use client";

import { CyclotronStatusView } from "cyclotron/components/cyclotron-status";
import { ChevronDownIcon, ClockIcon, GaugeIcon, Loader2Icon, RefreshCwIcon, TagsIcon, TargetIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import {
  NO_SNAPSHOT_SENTENCE, UNAVAILABLE_SENTENCE, describeClassifier,
  type HomeCyclotronState, type HostedStatusRow,
} from "../lib/hosted-cyclotron-status";

function Fact({ icon: Icon, children, ...rest }: { icon: LucideIcon; children: ReactNode } & Record<string, unknown>) {
  return (
    <li className="flex items-start gap-2" {...rest}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 break-words">{children}</span>
    </li>
  );
}

function ClassifierBlock({ row, timeZone }: { row: HostedStatusRow; timeZone?: string }) {
  const facts = describeClassifier(row, { timeZone });
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  return (
    <div className="space-y-2.5" data-home-cyclotron-classifier={facts.name}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Classifier: {facts.name}</p>
      <ul className="space-y-2">
        <Fact data-home-cyclotron-retraining icon={RefreshCwIcon}>{facts.retraining}</Fact>
        <Fact data-home-cyclotron-evaluation icon={TargetIcon}>
          <span className="font-semibold tabular-nums">{facts.evaluation}</span>
          <span className="block text-xs text-muted-foreground">{facts.evaluationNote}</span>
        </Fact>
        <Fact data-home-cyclotron-counts icon={TagsIcon}>{facts.counts.join(" · ")}</Fact>
        <Fact data-home-cyclotron-snapshot icon={ClockIcon}>
          {facts.snapshot}
          <span className="block text-xs text-muted-foreground">{facts.freshness}</span>
        </Fact>
      </ul>
      <button
        aria-controls={detailsId}
        aria-expanded={open}
        className="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-3 text-xs font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-home-cyclotron-details-toggle
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <ChevronDownIcon aria-hidden="true" className={cn("size-3.5 transition-transform", open && "rotate-180")} />
        {open ? "Hide classifier details" : "Classifier details"}
      </button>
      <div hidden={!open} id={detailsId}>
        {open ? <CyclotronStatusView classifierName="Relevant to this publication" status={row.status} variant="card" /> : null}
      </div>
    </div>
  );
}

/**
 * The Cyclotron classifier(s) that power this site's predictions, top right of the newsroom home page (phone: above the list).
 * One block per output, from this site's own publication only. `extra` is the seam for Cyclotron's proposed `report` operation
 * (history over time and the supporting questions behind a decision); nothing renders there until that operation is published and built.
 */
export function HomeCyclotronPanel({ cyclotron, extra = null, timeZone }: { cyclotron: HomeCyclotronState; extra?: ReactNode; timeZone?: string }) {
  let body: ReactNode;
  if (cyclotron.state === "loading") {
    body = <p className="flex items-center gap-2 text-muted-foreground" data-home-cyclotron-state="loading" role="status"><Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Reading the classifier&rsquo;s status.</p>;
  } else if (cyclotron.state === "unavailable") {
    body = <p className="flex items-start gap-2" data-home-cyclotron-state="unavailable" role="status"><TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{UNAVAILABLE_SENTENCE}</p>;
  } else if (cyclotron.state === "none") {
    body = <p data-home-cyclotron-state="none" role="status">{NO_SNAPSHOT_SENTENCE}</p>;
  } else {
    body = (
      <div className="space-y-4" data-home-cyclotron-state="ready">
        {cyclotron.rows.map((row) => <ClassifierBlock key={`${row.publicationId}:${row.output ?? row.status.cyclotron.id}`} row={row} timeZone={timeZone} />)}
        {extra}
      </div>
    );
  }
  return (
    <section
      aria-label="Cyclotron classifier"
      className="w-full min-w-0 space-y-3 rounded-[20px] bg-[var(--feed-card)] p-4 text-sm @3xl:w-[22rem] @3xl:shrink-0"
      data-home-cyclotron
    >
      <h2 className="inline-flex items-center gap-2 text-base font-bold tracking-tight"><GaugeIcon aria-hidden="true" className="size-4" />Cyclotron classifier</h2>
      {body}
    </section>
  );
}
