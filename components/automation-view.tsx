import Link from "next/link";
import { RunNowControl } from "./automation-run-now";
import {
  ENABLED_NOTE,
  OUTSIDE_NOTICE,
  costText,
  durationText,
  enabledText,
  formatUtc,
  linkText,
  noticeText,
  proceduresHref,
  statusMark,
  statusText,
  storyHref,
  triggerText,
  whoText,
  type AutomationOutsideRun,
  type AutomationRecord,
  type AutomationResult,
  type AutomationRun,
  type RunNowResult,
} from "../lib/automation-overview";

function Message({ title, children, kind }: { title: string; children?: React.ReactNode; kind: string }) {
  return (
    <div className="category-steering-empty" role={kind === "loading" ? "status" : "alert"} data-automation-state={kind}>
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

function RunLine({ run, demo }: { run: AutomationRun; demo: boolean }) {
  return (
    <li data-automation-run={run.runId ?? run.sourceId ?? "unlinked"} data-run-status={run.status ?? "unknown"}>
      <strong>{formatUtc(run.startedAt)}</strong>
      <span><span aria-hidden="true">{statusMark(run.status)} </span>Status: {statusText(run.status)} &middot; {durationText(run.durationSeconds)}</span>
      <span>{whoText(run)}</span>
      {run.reason ? <span data-automation-run-reason>Reason: {run.reason}</span> : null}
      {run.error ? <span data-automation-run-error>Error: {run.error}</span> : null}
      <span>
        {run.runId ? <>Run {run.runId} (<Link href={proceduresHref(demo)}>Procedures</Link>)</> : run.triggerStatus === "started" ? "Run record not linked yet" : "No run record"}
        {run.runRecord === "missing" ? " (the run record was not found)" : ""}
        {run.runRecord === "unavailable" ? " (the run record could not be read)" : ""}
      </span>
      <span>
        {run.storyId ? <>Story: <Link href={storyHref(run.storyId, demo)} data-automation-story-link>{run.storyTitle ?? run.storyId}</Link></> : "Story: none recorded"}
      </span>
      <span data-automation-run-cost data-over-budget={run.overBudget || undefined}>
        <span aria-hidden="true">{run.overBudget ? "! " : ""}</span>{costText(run)}
      </span>
    </li>
  );
}

function OutsideRunLine({ run, demo }: { run: AutomationOutsideRun; demo: boolean }) {
  return (
    <li data-automation-outside-run={run.runId ?? "unlinked"} data-run-status={run.status ?? "unknown"}>
      <strong>{formatUtc(run.startedAt)}</strong>
      <span><span aria-hidden="true">{statusMark(run.status)} </span>Status: {statusText(run.status)} &middot; {durationText(run.durationSeconds)}</span>
      <span>Started by: {run.requestedBy ?? "unknown"}</span>
      {run.error ? <span data-automation-run-error>Error: {run.error}</span> : null}
      <span>{run.runId ? <>Run {run.runId} (<Link href={proceduresHref(demo)}>Procedures</Link>)</> : "No run id"}</span>
      <span>
        {run.storyId ? <>Story: <Link href={storyHref(run.storyId, demo)}>{run.storyTitle ?? run.storyId}</Link></> : "Story: none recorded"}
      </span>
      <span data-automation-run-cost>{costText({ ...run, budgetUsd: null })}</span>
    </li>
  );
}

function Detail({ record, demo, onRunNow }: { record: AutomationRecord; demo: boolean; onRunNow?: RunNowHandler }) {
  const notice = noticeText(record.notice);
  return (
    <article className="news-desk-doctrine-card" data-automation-detail={record.id}>
      <div className="news-desk-doctrine-card__header"><div><h3>{record.title}</h3><span>{record.description ?? record.id}</span></div></div>
      <dl className="news-desk-monitoring__usage">
        <div><dt>Trigger</dt><dd>{triggerText(record.trigger)}{record.supported ? "" : ` (${record.supportNote ?? "not yet supported"})`}</dd></div>
        <div><dt>Procedure</dt><dd>{record.procedureKey}</dd></div>
        <div><dt>Input</dt><dd>{Object.keys(record.inputTemplate).length ? Object.entries(record.inputTemplate).map(([name, template]) => `${name} = ${template}`).join("; ") : "none"}</dd></div>
        <div><dt>Enabled</dt><dd>{enabledText(record)} ({ENABLED_NOTE})</dd></div>
        <div><dt>Limits</dt><dd>timeout {record.limits.timeoutSeconds ?? "?"} s, {record.limits.maxConcurrent ?? "?"} at a time{record.limits.budgetUsdPerRun !== undefined ? `, about $${record.limits.budgetUsdPerRun} per run, advisory` : ""} ({record.limitsNote})</dd></div>
        <div><dt>Router</dt><dd data-automation-link={record.link?.state ?? "unchecked"}>{linkText(record.link)}</dd></div>
      </dl>
      {notice ? <p className="news-desk-delegation-note" data-automation-notice>{notice}</p> : null}
      <RunNowControl record={record} demo={demo} onRun={onRunNow} />
      <h4>Recent runs</h4>
      {record.runs.length ? (
        <ul className="news-desk-monitoring__list" data-automation-runs>
          {record.runs.map((run) => <RunLine key={run.runId ?? `${run.sourceId}-${run.startedAt}`} run={run} demo={demo} />)}
        </ul>
      ) : <p data-automation-no-runs>No runs yet.</p>}
      {record.skippedAlreadyHadReference > 0 ? (
        <p className="news-desk-delegation-note" data-automation-skipped>
          {record.skippedAlreadyHadReference} {record.skippedAlreadyHadReference === 1 ? "item was" : "items were"} not started because the Reference already existed.
        </p>
      ) : null}
      {record.outsideRuns.length || record.outsideNotice ? (
        <>
          <h4>Started outside this automation</h4>
          <p className="news-desk-delegation-note">Other runs of {record.procedureKey} that this automation did not start.</p>
          {record.outsideNotice ? <p className="news-desk-delegation-note" data-automation-notice>{OUTSIDE_NOTICE}</p> : null}
          {record.outsideRuns.length ? (
            <ul className="news-desk-monitoring__list" data-automation-outside-runs>
              {record.outsideRuns.map((run) => <OutsideRunLine key={run.runId ?? run.startedAt ?? "run"} run={run} demo={demo} />)}
            </ul>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function ListItem({ record, selected, onSelect }: { record: AutomationRecord; selected: boolean; onSelect: (id: string) => void }) {
  const last = record.lastRun;
  return (
    <li data-automation={record.id}>
      <div>
        <strong>{record.title}</strong>
        <span>{triggerText(record.trigger)}{record.supported ? "" : ` (${record.supportNote ?? "not yet supported"})`}</span>
      </div>
      <span>Procedure: {record.procedureKey}</span>
      <span>{enabledText(record)} ({ENABLED_NOTE})</span>
      <span data-automation-last-run>
        Last run: <span aria-hidden="true">{statusMark(last?.status)} </span>{statusText(last?.status)}{last ? `, ${formatUtc(last.startedAt)}` : ""}
      </span>
      <button type="button" aria-pressed={selected} data-automation-select={record.id} onClick={() => onSelect(record.id)}>
        {selected ? "Showing runs" : "Show runs"}
      </button>
    </li>
  );
}

/** Presentation only: the panel fetches, this renders any result, so every state is testable from fixtures. */
export type RunNowHandler = (automationId: string, input: Record<string, unknown> | null) => Promise<RunNowResult>;

export function AutomationView({
  result,
  selectedId,
  onSelect,
  demo = false,
  onRunNow,
}: {
  result: AutomationResult | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  demo?: boolean;
  onRunNow?: RunNowHandler;
}) {
  let body: React.ReactNode;
  if (result === null) {
    body = <Message kind="loading" title="Loading automations" />;
  } else if ("error" in result) {
    body = result.error === "forbidden"
      ? <Message kind="forbidden" title="Automations are for editors and admins">Your account does not have access to this page. Ask an admin for the editor role.</Message>
      : <Message kind="error" title="Automations could not be read">The request was not understood. Reload the page.</Message>;
  } else if (result.state === "unavailable") {
    body = <Message kind="unavailable" title="Automations could not be read right now">Nothing is affected. Try again in a minute.</Message>;
  } else if (result.state === "empty") {
    body = <Message kind="empty" title="No automations yet">An operator creates one with <code>papyrus automations create</code>. Nothing is configured to run on its own from this page.</Message>;
  } else {
    const selected = result.automations.find((record) => record.id === selectedId) ?? (result.automations.length === 1 ? result.automations[0] : null);
    body = (
      <>
        <article className="news-desk-doctrine-card" data-automation-section="list">
          <div className="news-desk-doctrine-card__header"><div><h3>Automations</h3><span>What starts a procedure by itself</span></div></div>
          <ul className="news-desk-monitoring__list">
            {result.automations.map((record) => <ListItem key={record.id} record={record} selected={selected?.id === record.id} onSelect={onSelect} />)}
          </ul>
          {result.monitoring === "not_configured" ? <p className="news-desk-delegation-note" data-automation-notice>{noticeText("monitoring_not_configured")}</p> : null}
        </article>
        {selected ? <Detail record={selected} demo={demo} onRunNow={onRunNow} /> : <p className="news-desk-delegation-note" data-automation-pick>Choose an automation to see its recent runs.</p>}
      </>
    );
  }
  return (
    <div data-news-desk-admin-panel="automations">
      <article className="news-desk-doctrine-card">
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Automation</h3>
            <span>Procedures that start on their own. Editors and admins can run one now; an operator changes the settings with the command line.</span>
          </div>
        </div>
        {result && "asOf" in result ? <p className="news-desk-delegation-note" data-automation-as-of>As of {formatUtc(result.asOf)}. Enabled: {ENABLED_NOTE}.</p> : null}
      </article>
      {body}
    </div>
  );
}
