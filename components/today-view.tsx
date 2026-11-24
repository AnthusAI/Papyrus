import Link from "next/link";
import { useState } from "react";
import {
  AlarmClockCheckIcon, AlarmClockIcon, CalendarClockIcon, CheckIcon, ChevronDownIcon, CircleHelpIcon, ClockIcon, FlagIcon, HourglassIcon, LockIcon, MinusIcon, RotateCwIcon, SendIcon,
  TriangleAlertIcon, XIcon, type LucideIcon,
} from "lucide-react";
import { OUTCOME_MARKS, RunOutcome } from "./run-outcome";
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
  reviewRequestHref,
  runsText,
  sendCostText,
  sendItemsText,
  type OverdueWakeOutcome,
  type TodayCountKey,
  type TodayAttentionEntry,
  type TodayAttentionOverdue,
  type TodayDidNotRun,
  type TodayDue,
  type TodayOverview,
  type TodayResult,
  type TodayRow,
  type TodayReview,
  type TodayRun,
  type TodaySend,
} from "../lib/today-overview";

function Mark({ name }: { name: TodayCountKey }) {
  const Icon = OUTCOME_MARKS[name];
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
      <span className="font-medium"><RunOutcome outcome={outcome} shown={run.outcomeShown} /></span>
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

/** Acknowledges a run from Today: the run leaves the list. Says in words why when it could not. */
type Acknowledge = (runId: string) => Promise<string | null>;

const ACTION = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-full bg-[var(--feed-control)] px-4 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

function AcknowledgeAction({ runId, words, note, onAcknowledge }: { runId: string; words: string; note?: string | null; onAcknowledge?: Acknowledge }) {
  const [state, setState] = useState<{ busy: boolean; problem: string | null }>({ busy: false, problem: null });
  const act = async () => {
    if (!onAcknowledge) return;
    setState({ busy: true, problem: null });
    const problem = await onAcknowledge(runId);
    setState({ busy: false, problem });
  };
  return (
    <span className="flex flex-col items-start gap-1">
      <button className={ACTION} data-today-action={words.toLowerCase()} data-today-action-run={runId} disabled={state.busy || !onAcknowledge} onClick={act} title={note ?? undefined} type="button">
        <CheckIcon aria-hidden="true" className="size-4 shrink-0" />
        {state.busy ? `${words}…` : words}
      </button>
      {state.problem ? <span className="text-xs" data-today-action-problem role="alert">{state.problem}</span> : null}
    </span>
  );
}

function ItemCard({ children, attributes }: { children: React.ReactNode; attributes: Record<string, string> }) {
  return (
    <li className="flex flex-col gap-3 rounded-[16px] bg-[var(--feed-card)] p-3 text-sm sm:flex-row sm:items-start sm:justify-between" {...attributes}>
      {children}
    </li>
  );
}

function Status({ icon: Icon, words }: { icon: LucideIcon; words: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-medium" data-today-status>
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      {words}
    </span>
  );
}

function ReviewItem({ entry, demo }: { entry: TodayReview; demo: boolean }) {
  const flag = entry.mode === "flag";
  return (
    <ItemCard attributes={{ "data-today-review": entry.id, "data-today-review-mode": entry.mode }}>
      <div className="min-w-0 space-y-1">
        <Status icon={flag ? FlagIcon : CircleHelpIcon} words={entry.modeWords} />
        <p className="break-words font-semibold">{entry.reason}</p>
        <p className="break-words text-xs text-muted-foreground">
          {entry.subjectWords}
          {entry.mode === "soft_review" && entry.deadlineLocal ? ` · goes on without review at ${entry.deadlineLocal}` : ""}
        </p>
      </div>
      <Link className={ACTION} data-today-action={entry.action.kind} href={reviewRequestHref(entry.id, demo)}>
        {flag ? <FlagIcon aria-hidden="true" className="size-4 shrink-0" /> : <CircleHelpIcon aria-hidden="true" className="size-4 shrink-0" />}
        {entry.action.words}
      </Link>
    </ItemCard>
  );
}

/** Wake now on an Overdue record: its own timer's wake goes on the site's queue again, with the same key. Says what happened in words beside a mark. */
type WakeOverdue = (record: string, id: string, reason: string) => Promise<OverdueWakeOutcome>;

export function WakeOverdueAction({ entry, onWakeOverdue, initialOutcome = null }: { entry: TodayAttentionOverdue; onWakeOverdue?: WakeOverdue; initialOutcome?: OverdueWakeOutcome | null }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<OverdueWakeOutcome | null>(initialOutcome);
  const act = async () => {
    if (!onWakeOverdue) return;
    if (!reason.trim()) {
      setOutcome({ state: "refused", words: "Say why it is woken now: the reason is kept on its run. Nothing was sent." });
      return;
    }
    setBusy(true);
    setOutcome(await onWakeOverdue(entry.record, entry.id, reason));
    setBusy(false);
  };
  const OutcomeIcon = outcome?.state === "sent" ? AlarmClockCheckIcon : TriangleAlertIcon;
  return (
    <span className="flex flex-col items-start gap-1.5 sm:max-w-[16rem]">
      <label className="flex w-full flex-col gap-1 text-xs font-medium">
        Reason
        <input className="min-h-11 w-full rounded-full bg-[var(--feed-control)] px-4 text-sm font-normal outline-none focus-visible:ring-2 focus-visible:ring-ring" data-today-wake-reason
          onChange={(event) => setReason(event.target.value)} placeholder="Why now" type="text" value={reason} />
      </label>
      <button className={ACTION} data-today-action="wake_now" data-today-action-id={entry.id} data-today-action-record={entry.record}
        disabled={busy || !onWakeOverdue || entry.action.available === false} onClick={act} type="button">
        <AlarmClockIcon aria-hidden="true" className="size-4 shrink-0" />
        {busy ? "Waking…" : entry.action.words}
      </button>
      {outcome ? (
        <span className="inline-flex items-start gap-1.5 text-xs" data-today-wake-outcome={outcome.state} role={outcome.state === "sent" ? "status" : "alert"}>
          <OutcomeIcon aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          {outcome.words}
        </span>
      ) : entry.action.note ? <span className="text-xs text-muted-foreground" data-today-action-note>{entry.action.note}</span> : null}
    </span>
  );
}

function AttentionItem({ entry, demo, onAcknowledge, onWakeOverdue }: { entry: TodayAttentionEntry; demo: boolean; onAcknowledge?: Acknowledge; onWakeOverdue?: WakeOverdue }) {
  if (entry.kind === "review") return <ReviewItem demo={demo} entry={entry} />;
  if (entry.kind === "overdue") {
    return (
      <ItemCard attributes={{ "data-today-overdue": entry.id, "data-today-overdue-kind": entry.record }}>
        <div className="min-w-0 space-y-1">
          <Status icon={AlarmClockIcon} words="Overdue" />
          <p className="break-words font-semibold">{entry.record} {entry.id}</p>
          <p className="text-xs text-muted-foreground">was due {entry.dueLocal ?? entry.dueAt}{entry.waitingFor ? ` (${entry.waitingFor})` : ""} and nothing ran</p>
        </div>
        <WakeOverdueAction entry={entry} onWakeOverdue={onWakeOverdue} />
      </ItemCard>
    );
  }
  return (
    <ItemCard attributes={{ "data-today-attention-run": entry.id, "data-today-attention-outcome": entry.outcome }}>
      <div className="min-w-0 space-y-1">
        <Status icon={entry.outcome === "unknown" ? TriangleAlertIcon : XIcon} words={entry.reason ? `${entry.words} (${entry.reason})` : entry.words} />
        <p className="break-words font-semibold">{entry.title}{entry.subjectWords ? ` · ${entry.subjectWords}` : ""}</p>
        <p className="break-all text-xs text-muted-foreground">Run {entry.id}{entry.neededLocal ? ` · since ${entry.neededLocal}` : ""}</p>
        {entry.error ? <p className="break-words text-xs" data-today-attention-error>Error: {entry.error}</p> : null}
        {entry.action.note ? <p className="text-xs text-muted-foreground" data-today-action-note>{entry.action.note}</p> : null}
      </div>
      <AcknowledgeAction note={entry.action.note} onAcknowledge={onAcknowledge} runId={entry.id} words={entry.action.words} />
    </ItemCard>
  );
}

/** Each kind of due time has its own mark beside its words. */
const DUE_MARKS: Record<TodayDue["what"], LucideIcon> = {
  lockAt: LockIcon, releaseAt: SendIcon, nextAttemptAt: RotateCwIcon, scheduledPublishAt: CalendarClockIcon, schedule: ClockIcon, deadline: HourglassIcon,
};

function DueLine({ entry }: { entry: TodayDue }) {
  const Icon = DUE_MARKS[entry.what] ?? ClockIcon;
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-[16px] bg-[var(--feed-card)] p-3 text-sm" data-today-due={entry.id} data-today-due-what={entry.what}>
      <span className="w-20 shrink-0 font-semibold tabular-nums" data-today-due-local>{entry.local}</span>
      <span className="inline-flex items-center gap-1.5 font-medium">
        <Icon aria-hidden="true" className="size-4 shrink-0" />
        {entry.words}
      </span>
      <span className="break-words">{entry.title}</span>
      {entry.detail ? <span className="text-xs text-muted-foreground">{entry.detail}</span> : null}
    </li>
  );
}

function Heading({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {children}{count === undefined ? null : <span className="tabular-nums"> ({count})</span>}
    </h3>
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

function Ready({ overview, demo, onAcknowledge, onWakeOverdue }: { overview: TodayOverview; demo: boolean; onAcknowledge?: Acknowledge; onWakeOverdue?: WakeOverdue }) {
  return (
    <>
      {overview.timeZoneNote ? <p className="text-sm" data-today-zone-note>{overview.timeZoneNote}</p> : null}
      <Heading count={overview.waiting.length}>Waiting for you</Heading>
      {overview.waiting.length ? (
        <ul className="space-y-2" data-today-waiting>
          {overview.waiting.map((entry) => <ReviewItem demo={demo} entry={entry} key={entry.id} />)}
        </ul>
      ) : <p className="text-sm text-muted-foreground" data-today-nothing-waiting>Nothing is waiting for you.</p>}
      <Heading count={overview.attention.length}>Needs attention</Heading>
      {overview.attention.length ? (
        <ul className="space-y-2" data-today-attention>
          {overview.attention.map((entry) => <AttentionItem demo={demo} entry={entry} key={`${entry.kind}:${entry.id}`} onAcknowledge={onAcknowledge} onWakeOverdue={onWakeOverdue} />)}
        </ul>
      ) : <p className="text-sm text-muted-foreground" data-today-nothing-attention>Nothing needs attention.</p>}
      <Heading count={overview.due.length}>Due today</Heading>
      {overview.due.length ? (
        <ul className="space-y-2" data-today-due-list>
          {overview.due.map((entry) => <DueLine entry={entry} key={`${entry.kind}:${entry.id}:${entry.what}:${entry.at}`} />)}
        </ul>
      ) : <p className="text-sm text-muted-foreground" data-today-nothing-due>Nothing is due in this day.</p>}
      <p className="text-sm text-muted-foreground" data-today-summary role="status">
        {runsText(overview.totals.runs)} · {costText(overview.totals)}
      </p>
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

/** The Today section of the newsroom home: what only a person can move first, then what is due, then what ran. The panel around it refreshes it,
 *  acknowledges runs and wakes Overdue records now. */
export function TodayView({ result, demo = false, onAcknowledge, onWakeOverdue }: { result: TodayResult | null; demo?: boolean; onAcknowledge?: Acknowledge; onWakeOverdue?: WakeOverdue }) {
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
        : <Ready demo={demo} onAcknowledge={onAcknowledge} onWakeOverdue={onWakeOverdue} overview={result} />}
    </section>
  );
}
