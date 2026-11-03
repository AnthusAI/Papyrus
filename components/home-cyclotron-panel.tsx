"use client";

import { CyclotronStatusView } from "cyclotron/components/cyclotron-status";
import {
  CalendarDaysIcon, ChevronDownIcon, ClockIcon, FlaskConicalIcon, GaugeIcon, GraduationCapIcon, HandshakeIcon, ListChecksIcon, Loader2Icon,
  RefreshCwIcon, TagsIcon, TargetIcon, TriangleAlertIcon, type LucideIcon,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import {
  NO_SNAPSHOT_SENTENCE, UNAVAILABLE_SENTENCE, describeClassifier, describeReport, outputOf,
  type ClassifierReport, type HomeCyclotronState, type HostedStatusRow,
} from "../lib/hosted-cyclotron-status";

function Fact({ icon: Icon, children, ...rest }: { icon: LucideIcon; children: ReactNode } & Record<string, unknown>) {
  return (
    <li className="flex items-start gap-2" {...rest}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 break-words">{children}</span>
    </li>
  );
}

/** The rubric is long text: shown wrapped, and folded away when it is very long. Always text, never HTML. */
const RUBRIC_FOLD_CHARACTERS = 500;

function Rubric({ text }: { text: string }) {
  const body = <p className="whitespace-pre-wrap break-words" data-home-cyclotron-rubric-text>{text}</p>;
  if (text.length <= RUBRIC_FOLD_CHARACTERS) return body;
  return (
    <details data-home-cyclotron-rubric-fold>
      <summary className="inline-flex min-h-9 cursor-pointer items-center rounded-full bg-[var(--feed-control)] px-3 text-xs font-medium">Show the rubric ({text.length} characters)</summary>
      <div className="mt-2">{body}</div>
    </details>
  );
}

/** The decision elements behind the classification, from the report. */
function DecisionElements({ report, timeZone }: { report: ClassifierReport; timeZone?: string }) {
  const facts = describeReport(report, { timeZone });
  return (
    <div className="space-y-3 rounded-2xl bg-[var(--feed-control)] p-3" data-home-cyclotron-elements>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">What the classifier asks</p>
      <div className="space-y-1" data-home-cyclotron-question>
        <p className="text-xs text-muted-foreground">Question{report.classifier.revision != null ? ` (classifier revision ${report.classifier.revision})` : ""}</p>
        <p className="whitespace-pre-wrap break-words">{facts.question}</p>
      </div>
      <div className="space-y-1" data-home-cyclotron-classes>
        <p className="text-xs text-muted-foreground">Classes</p>
        <p className="break-words">{facts.classes || "No classes reported."}</p>
      </div>
      <div className="space-y-1" data-home-cyclotron-rubric>
        <p className="text-xs text-muted-foreground">Rubric</p>
        {facts.rubric ? <Rubric text={facts.rubric} /> : <p>No rubric is set for this classifier.</p>}
      </div>
      <div className="space-y-1" data-home-cyclotron-supporting>
        <p className="text-xs text-muted-foreground">Supporting questions and weights</p>
        {facts.supporting.rows.length ? (
          <ul className="space-y-1">
            {facts.supporting.rows.map((entry) => (
              <li className="flex items-start justify-between gap-3" key={entry.name}>
                <span className="min-w-0 break-words">{entry.name}</span>
                {entry.weight !== null ? <span className="shrink-0 tabular-nums">weight {entry.weight}</span> : null}
              </li>
            ))}
          </ul>
        ) : <p>None yet. {facts.supporting.reason}</p>}
      </div>
      {facts.awaiting ? <p className="text-xs text-muted-foreground" data-home-cyclotron-awaiting>{facts.awaiting}</p> : null}
      {facts.trimmed ? <p className="text-xs text-muted-foreground" data-home-cyclotron-trimmed>{facts.trimmed}</p> : null}
    </div>
  );
}

/** Agreement by day: a mark and words for each day, so nothing depends on colour. A single day shows no trend. */
function DaysList({ facts }: { facts: ReturnType<typeof describeReport> }) {
  return (
    <div className="space-y-1.5" data-home-cyclotron-days>
      <ul className="space-y-1">
        {facts.days.map((day) => (
          <li className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 text-xs @3xl:grid-cols-[5.5rem_minmax(0,1fr)]" data-home-cyclotron-day={day.day} key={day.day}>
            <span className="tabular-nums">{day.label}</span>
            <span className="flex min-w-0 items-center gap-2">
              <span aria-hidden="true" className="h-2 w-16 shrink-0 overflow-hidden rounded-full bg-[var(--feed-control)]">
                <span className="block h-full rounded-full bg-foreground/70" style={{ width: `${Math.round((day.share ?? 0) * 100)}%` }} />
              </span>
              <span className="min-w-0 break-words tabular-nums">{day.words}</span>
            </span>
          </li>
        ))}
      </ul>
      {facts.earlierDays > 0 ? <p className="text-xs text-muted-foreground">{facts.earlierDays} earlier {facts.earlierDays === 1 ? "day is" : "days are"} not shown.</p> : null}
      <p className="text-xs text-muted-foreground" data-home-cyclotron-days-note>{facts.daysNote}</p>
    </div>
  );
}

function ReportFacts({ report, timeZone, withSnapshot }: { report: ClassifierReport; timeZone?: string; withSnapshot: boolean }) {
  const facts = describeReport(report, { timeZone });
  return (
    <>
      <Fact data-home-cyclotron-learning icon={GraduationCapIcon}>
        <span className="font-semibold">{facts.learning}</span>
        {facts.learningReason ? <span className="block text-xs text-muted-foreground">{facts.learningReason}</span> : null}
      </Fact>
      <Fact data-home-cyclotron-retraining icon={RefreshCwIcon}>
        {facts.cycle}
        {facts.version ? <span className="block text-xs text-muted-foreground">{facts.version}</span> : null}
      </Fact>
      <Fact data-home-cyclotron-agreement icon={HandshakeIcon}>
        <span className="font-semibold tabular-nums">{facts.agreement}</span>
        <span className="block text-xs text-muted-foreground">{facts.agreementNote}</span>
      </Fact>
      <Fact data-home-cyclotron-over-time icon={CalendarDaysIcon}>
        <span className="block text-xs font-medium text-muted-foreground">Over time</span>
        {facts.days.length ? <DaysList facts={facts} /> : <span className="block text-xs text-muted-foreground">{facts.daysNote}</span>}
        {facts.revisions.length ? (
          <ul className="mt-1.5 space-y-0.5 text-xs" data-home-cyclotron-revisions>
            {facts.revisions.map((line) => <li className="break-words" key={line}>{line}</li>)}
          </ul>
        ) : null}
      </Fact>
      <Fact data-home-cyclotron-held-out icon={FlaskConicalIcon}>{facts.heldOut}</Fact>
      <Fact data-home-cyclotron-counts icon={TagsIcon}>{facts.counts.join(" · ")}</Fact>
      {withSnapshot ? null : <Fact data-home-cyclotron-snapshot icon={ClockIcon}>{facts.snapshot}</Fact>}
    </>
  );
}

function ClassifierBlock({ row, timeZone }: { row: HostedStatusRow; timeZone?: string }) {
  const { status, report } = row;
  const facts = status ? describeClassifier({ ...row, status }, { timeZone }) : null;
  const name = facts?.name ?? report?.classifier.id ?? outputOf(row);
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  return (
    <div className="space-y-2.5" data-home-cyclotron-classifier={name}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Classifier: {name}</p>
      <ul className="space-y-2">
        {report ? <ReportFacts report={report} timeZone={timeZone} withSnapshot={facts !== null} /> : null}
        {facts && !report ? (
          <>
            <Fact data-home-cyclotron-retraining icon={RefreshCwIcon}>{facts.retraining}</Fact>
            <Fact data-home-cyclotron-evaluation icon={TargetIcon}>
              <span className="font-semibold tabular-nums">{facts.evaluation}</span>
              <span className="block text-xs text-muted-foreground">{facts.evaluationNote}</span>
            </Fact>
            <Fact data-home-cyclotron-counts icon={TagsIcon}>{facts.counts.join(" · ")}</Fact>
          </>
        ) : null}
        {facts ? (
          <Fact data-home-cyclotron-snapshot icon={ClockIcon}>
            {facts.snapshot}
            <span className="block text-xs text-muted-foreground">{facts.freshness}</span>
          </Fact>
        ) : null}
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
      <div className="space-y-3" hidden={!open} id={detailsId}>
        {open && report ? <DecisionElements report={report} timeZone={timeZone} /> : null}
        {open && status ? <CyclotronStatusView classifierName="Relevant to this publication" status={status} variant="card" /> : null}
        {open && report && !status ? (
          <p className="flex items-start gap-2 text-xs text-muted-foreground"><ListChecksIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />The Cyclotron has completed no decision for this classifier yet, so there is no status snapshot.</p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The Cyclotron classifier(s) that power this site's predictions, top right of the newsroom home page (phone: above the list).
 * One block per output, from this site's own publication only. With a report (`cyclotron-classifier-report/v1`) the top shows learning, the most
 * recent cycle, agreement with reviewers, agreement by day, the held-out evaluation and label counts, and the expanded details add the decision elements
 * (question, classes, rubric, supporting questions and weights). Without one (an older site, or before the router's first run) it shows the status
 * snapshot's facts alone. `extra` is a slot after the blocks for anything else.
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
        {cyclotron.rows.map((row) => <ClassifierBlock key={`${row.publicationId}:${outputOf(row)}`} row={row} timeZone={timeZone} />)}
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
