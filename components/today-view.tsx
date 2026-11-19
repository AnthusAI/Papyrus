import Link from "next/link";
import { AlarmClockIcon, CheckIcon, ChevronDownIcon, CircleHelpIcon, ClockIcon, MinusIcon, TriangleAlertIcon, XIcon, type LucideIcon } from "lucide-react";
import {
  OTHER_ORDER,
  OUTCOME_ORDER,
  OUTCOME_WORDS,
  SEND_COUNT_ORDER,
  SEND_COUNT_WORDS,
  automationsHref,
  costText,
  countWords,
  dayTitle,
  reasonsText,
  runsText,
  sendCostText,
  sendItemsText,
  type TodayCountKey,
  type TodayDidNotRun,
  type TodayOverdue,
  type TodayOverview,
  type TodayResult,
  type TodayRow,
  type TodayRun,
  type TodaySend,
} from "../lib/today-overview";

/** Every status is a mark and its words, never a colour alone. The marks are Lucide icons; the words come with them. */
const MARKS: Record<TodayCountKey, LucideIcon> = {
  acted: CheckIcon,
  nothing: MinusIcon,
  asked: CircleHelpIcon,
  failed: XIcon,
  unknown: TriangleAlertIcon,
  notFinished: ClockIcon,
  beforeOutcomes: MinusIcon,
};

function Mark({ name }: { name: TodayCountKey }) {
  const Icon = MARKS[name];
  return <Icon aria-hidden="true" className="size-3.5 shrink-0" />;
}

const CHIP = "inline-flex items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-2.5 py-1 text-xs";

function Message({ title, children, kind }: { title: string; children?: React.ReactNode; kind: string }) {
  return (
    <div className="rounded-[16px] bg-[var(--feed-card)] p-4 text-sm" data-today-state={kind} role={kind === "loading" ? "status" : "alert"}>
      <strong>{title}</strong>
      {children ? <p className="mt-1 text-muted-foreground">{children}</p> : null}
    </div>
  );
}

function RunLine({ run }: { run: TodayRun }) {
  const outcome = run.outcome ?? (run.runStatus === "completed" || run.runStatus === "failed" ? "beforeOutcomes" : "notFinished");
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" data-today-run={run.runId ?? "unlinked"} data-today-run-outcome={outcome}>
      <span className="inline-flex items-center gap-1.5 font-medium">
        <Mark name={outcome} />
        {run.outcomeShown}
      </span>
      <span className="tabular-nums text-muted-foreground">{run.requestedAt ? run.requestedAt.slice(11, 16) + " UTC" : "time not recorded"}</span>
      <span className="text-muted-foreground">{run.costUsd === null ? "cost unknown" : costText({ costUsd: run.costUsd, costKnownRuns: 1, costUnknownRuns: 0 })}</span>
      <span className="break-all text-muted-foreground">{run.runId ? `Run ${run.runId}` : "No run id"}</span>
      {run.error ? <span className="break-words" data-today-run-error>Error: {run.error}</span> : null}
    </li>
  );
}

function Row({ row, demo }: { row: TodayRow; demo: boolean }) {
  const counted = [...OUTCOME_ORDER, ...OTHER_ORDER].filter((key) => row.counts[key] > 0);
  const reasons = OUTCOME_ORDER.filter((outcome) => row.reasons[outcome] && Object.keys(row.reasons[outcome] ?? {}).length);
  return (
    <li className="space-y-2 rounded-[16px] bg-[var(--feed-card)] p-3" data-today-row={row.key}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold">{row.title}</h3>
        <span className="text-xs tabular-nums text-muted-foreground" data-today-row-cost>{runsText(row.runs.length)} · {costText(row)}</span>
      </div>
      <ul className="flex flex-wrap gap-1.5" data-today-counts>
        {counted.map((key) => (
          <li className={CHIP} data-today-count={key} key={key}>
            <Mark name={key} />
            <span>{countWords(key)}</span>
            <strong className="tabular-nums">{row.counts[key]}</strong>
          </li>
        ))}
      </ul>
      {reasons.length ? (
        <ul className="space-y-0.5 text-xs" data-today-reasons>
          {reasons.map((outcome) => (
            <li className="flex flex-wrap items-center gap-1.5" data-today-reason={outcome} key={outcome}>
              <Mark name={outcome} />
              <span className="font-medium">{OUTCOME_WORDS[outcome]}:</span>
              <span className="break-words">{reasonsText(row.reasons[outcome] ?? {})}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <details className="group text-xs" data-today-runs>
        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-1.5 font-medium text-muted-foreground">
          <ChevronDownIcon aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-180" />
          Show the {runsText(row.runs.length)}
        </summary>
        <ul className="space-y-2 pb-1 pt-1">
          {row.runs.map((run) => <RunLine key={run.runId ?? `${run.requestedAt}`} run={run} />)}
        </ul>
        {row.automationIds.length ? (
          <p className="flex flex-wrap gap-x-4 gap-y-1">
            {row.automationIds.map((id) => (
              <Link className="underline underline-offset-2" data-today-open-runs={id} href={automationsHref(id, demo)} key={id}>Open the runs of {id}</Link>
            ))}
          </p>
        ) : (
          <p><Link className="underline underline-offset-2" data-today-open-runs href={automationsHref(null, demo)}>Open Automations</Link></p>
        )}
      </details>
    </li>
  );
}

/** Where a send stands: a mark and its words, never colour alone. A state the table does not name is shown by its words with the neutral mark. */
const SEND_MARKS: Record<string, LucideIcon> = {
  sent: CheckIcon, sending: ClockIcon, ready: ClockIcon, drafted: ClockIcon, blocked: TriangleAlertIcon, failed: XIcon, dry_run: MinusIcon, withdrawn: MinusIcon, superseded: MinusIcon,
};

function SendLine({ send }: { send: TodaySend }) {
  const Icon = SEND_MARKS[send.state] ?? MinusIcon;
  const counted = SEND_COUNT_ORDER.filter((key) => send.counts[key] > 0);
  return (
    <li className="space-y-2 rounded-[16px] bg-[var(--feed-card)] p-3" data-today-send={send.deliveryId} data-today-send-state={send.state}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold">{send.lists.length ? send.lists.join(", ") : "No lists"}</h3>
        <span className="text-xs tabular-nums text-muted-foreground" data-today-send-items-cost>{sendItemsText(send.items)} · {sendCostText(send.cost)}</span>
      </div>
      <p className="inline-flex items-center gap-1.5 text-xs font-medium" data-today-send-status>
        <Icon aria-hidden="true" className="size-3.5 shrink-0" />
        {send.stateWords}
      </p>
      {counted.length ? (
        <ul className="flex flex-wrap gap-1.5" data-today-send-counts>
          {counted.map((key) => (
            <li className={CHIP} data-today-send-count={key} key={key}>
              <span>{SEND_COUNT_WORDS[key]}</span>
              <strong className="tabular-nums">{send.counts[key]}</strong>
            </li>
          ))}
        </ul>
      ) : <p className="text-xs text-muted-foreground" data-today-send-no-readers>No readers yet.</p>}
    </li>
  );
}

function OverdueLine({ entry }: { entry: TodayOverdue }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[16px] bg-[var(--feed-card)] p-3 text-sm" data-today-overdue={entry.id} data-today-overdue-kind={entry.kind}>
      <span className="inline-flex items-center gap-1.5 font-medium">
        <AlarmClockIcon aria-hidden="true" className="size-3.5 shrink-0" />
        Overdue
      </span>
      <span>{entry.kind} {entry.id}</span>
      <span className="text-xs text-muted-foreground">was due {entry.dueAt}{entry.waitingFor ? ` (${entry.waitingFor})` : ""} and nothing ran</span>
    </li>
  );
}

function DidNotRunLine({ entry, demo }: { entry: TodayDidNotRun; demo: boolean }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[16px] bg-[var(--feed-card)] p-3 text-sm" data-today-did-not-run={entry.automationId} data-today-why={entry.whyCode}>
      <span className="inline-flex items-center gap-1.5 font-medium">
        <MinusIcon aria-hidden="true" className="size-3.5 shrink-0" />
        {entry.title}
      </span>
      <span>{entry.state}</span>
      <span className="text-xs text-muted-foreground">{entry.why}</span>
      <Link className="text-xs underline underline-offset-2" href={automationsHref(entry.automationId, demo)}>Open</Link>
    </li>
  );
}

function Ready({ overview, demo }: { overview: TodayOverview; demo: boolean }) {
  return (
    <>
      <p className="text-sm text-muted-foreground" data-today-summary role="status">
        {runsText(overview.totals.runs)} · {costText(overview.totals)}
      </p>
      {overview.overdue.length ? (
        <>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Needs attention</h3>
          <ul className="space-y-2" data-today-overdue-list>
            {overview.overdue.map((entry) => <OverdueLine entry={entry} key={`${entry.kind}:${entry.id}`} />)}
          </ul>
        </>
      ) : null}
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">What ran</h3>
      {overview.rows.length ? (
        <ul className="space-y-2" data-today-rows>
          {overview.rows.map((row) => <Row demo={demo} key={row.key} row={row} />)}
        </ul>
      ) : <p className="text-sm text-muted-foreground" data-today-nothing-ran>Nothing ran in this day.</p>}
      {overview.sends.length ? (
        <>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Sends</h3>
          <ul className="space-y-2" data-today-sends>
            {overview.sends.map((send) => <SendLine key={send.deliveryId} send={send} />)}
          </ul>
        </>
      ) : null}
      {overview.didNotRun.length ? (
        <>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Did not run</h3>
          <ul className="space-y-2" data-today-did-not-run-list>
            {overview.didNotRun.map((entry) => <DidNotRunLine demo={demo} entry={entry} key={entry.automationId} />)}
          </ul>
        </>
      ) : null}
    </>
  );
}

/** The Today section of the newsroom home. Read only; the panel around it refreshes it. */
export function TodayView({ result, demo = false }: { result: TodayResult | null; demo?: boolean }) {
  return (
    <section aria-label="Today" className="space-y-3" data-today>
      <h2 className="text-lg font-semibold">
        Today
        {result && "state" in result && result.state === "ready" ? <span className="ml-2 text-sm font-normal text-muted-foreground" data-today-day>{dayTitle(result.day)} · {result.timeZone}</span> : null}
      </h2>
      {result === null ? <Message kind="loading" title="Loading what ran today" />
        : "error" in result ? (
          result.error === "forbidden"
            ? <Message kind="forbidden" title="Today is for editors and admins">Your account can read the rest of this page, not what the agents did.</Message>
            : <Message kind="bad_request" title="Today could not be read">{result.message ?? "The request was not understood."}</Message>
        )
        : result.state === "unavailable" ? <Message kind="unavailable" title="Today could not be read right now">Nothing is wrong with what you see elsewhere on this page. It tries again by itself.</Message>
        : <Ready demo={demo} overview={result} />}
    </section>
  );
}
