import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import {
  confidenceText,
  describeDelivery,
  describeRelevance,
  everyText,
  formatUtc,
  referenceHref,
  routingLabel,
  beginEmailSubmissionAction,
  endEmailSubmissionAction,
  isCurrentEmailSubmissionAction,
  type MonitoringItem,
  type MonitoringEmailDetails,
  type MonitoringEmailArticleResolution,
  type EmailReferenceImportItem,
  type EmailReferenceImportOutcome,
  type MonitoringEmailSummary,
  type MonitoringOverview,
  type MonitoringRelevance,
  type MonitoringResult,
} from "../lib/monitoring-overview";

export type MonitoringMode = "publication" | "all";

const STATUS_WORDS: Record<string, string> = { complete: "Complete", partial: "Partial", stopped: "Stopped", failed: "Failed", error: "Error" };
const status = (value: string) => STATUS_WORDS[value] ?? value;
const STOP_WORDS: Record<string, string> = {
  request_ceiling_reached: "stopped at the request ceiling",
  standing_capacity_reached: "stopped: the standing run is full",
  provider_key_unavailable: "stopped: the Cyclotron has no model key",
  run_busy: "stopped: the Cyclotron run was busy",
  time_budget: "stopped for time",
};
const MARKS: Record<string, string> = { delivered: "✓", failed: "✕", pending: "…", not_applicable: "–" };

function feedHost(url: string | null): string {
  try {
    return url ? new URL(url).host : "unknown source";
  } catch {
    return "unknown source";
  }
}

function Message({ title, children, kind }: { title: string; children?: React.ReactNode; kind: string }) {
  return (
    <div className="category-steering-empty" role={kind === "loading" ? "status" : "alert"} data-monitoring-state={kind}>
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

function RelevanceLine({ entry, linkable, demo }: { entry: MonitoringRelevance; linkable: boolean; demo: boolean }) {
  const lineage = entry.delivery.referenceLineageId ?? entry.delivery.referenceId ?? null;
  const delivery = describeDelivery(entry);
  return (
    <li data-relevance={entry.relevant === null ? "unknown" : entry.relevant ? "yes" : "no"} data-delivery={entry.delivery.state ?? "none"}>
      <strong>{entry.publicationId}</strong>
      <span>{describeRelevance(entry)}{entry.relevant !== null ? `, ${confidenceText(entry.confidence)}` : ""}</span>
      {delivery ? (
        <span>
          <span aria-hidden="true">{MARKS[entry.delivery.state ?? ""] ?? ""} </span>
          {delivery}
          {entry.delivery.state === "delivered" && lineage && linkable ? (
            <> <Link href={referenceHref(lineage, demo)} data-monitoring-reference-link>Open in References</Link></>
          ) : null}
          {entry.delivery.state === "failed" && entry.delivery.error ? <> ({entry.delivery.error})</> : null}
        </span>
      ) : null}
    </li>
  );
}

function QueueItem({ item, ownId, demo }: { item: MonitoringItem; ownId: string | null; demo: boolean }) {
  return (
    <li data-monitoring-item={item.sourceId} data-routing={item.routing}>
      <div>
        <strong>{item.url ? <a href={item.url} target="_blank" rel="noreferrer noopener">{item.title}</a> : item.title}</strong>
        <span>
          {formatUtc(item.observedAt)}
          {item.discussionUrl ? <> &middot; <a href={item.discussionUrl} target="_blank" rel="noreferrer noopener">Hacker News thread</a></> : null}
        </span>
      </div>
      <p className="news-desk-monitoring__routing">
        {routingLabel(item.routing)}
        {item.routingNote ? <>: {item.routingNote}</> : null}
      </p>
      {item.relevance.length ? (
        <ul className="news-desk-monitoring__relevance">
          {item.relevance.map((entry) => <RelevanceLine key={entry.publicationId} entry={entry} linkable={entry.publicationId === ownId} demo={demo} />)}
        </ul>
      ) : null}
    </li>
  );
}

export function EmailSubmissions({ items, detail, onOpen, onResolveArticleLink, onImportCandidates }: {
  items: MonitoringEmailSummary[]; detail: MonitoringEmailDetails | null; onOpen?: (receiptId: string) => void;
  onResolveArticleLink?: (receiptId: string, candidateIndex: number) => Promise<MonitoringEmailArticleResolution>;
  onImportCandidates?: (receiptId: string, items: EmailReferenceImportItem[]) => Promise<EmailReferenceImportOutcome>;
}) {
  const [selectedByReceipt, setSelectedByReceipt] = useState<Record<string, Record<number, boolean>>>({});
  const [resolvedByReceipt, setResolvedByReceipt] = useState<Record<string, Record<number, { url: string; title: string }>>>({});
  const [busyIndexByReceipt, setBusyIndexByReceipt] = useState<Record<string, number | null>>({});
  const [busyImportByReceipt, setBusyImportByReceipt] = useState<Record<string, boolean>>({});
  const [noticeByReceipt, setNoticeByReceipt] = useState<Record<string, string>>({});
  const [importedByReceipt, setImportedByReceipt] = useState<Record<string, EmailReferenceImportOutcome["references"]>>({});
  const receiptId = detail && "submission" in detail ? detail.submission.receiptId : null;
  const receiptKey = receiptId ?? "";
  const selected = selectedByReceipt[receiptKey] ?? {};
  const resolved = resolvedByReceipt[receiptKey] ?? {};
  const busyIndex = busyIndexByReceipt[receiptKey] ?? null;
  const busyImport = busyImportByReceipt[receiptKey] ?? false;
  const notice = noticeByReceipt[receiptKey] ?? "";
  const importedReferences = importedByReceipt[receiptKey] ?? [];
  const activeReceiptId = useRef<string | null>(receiptId);
  activeReceiptId.current = receiptId;
  const inFlightActions = useRef(new Set<string>());
  useEffect(() => {
    if (!detail || !("submission" in detail)) return;
    setSelectedByReceipt((current) => current[receiptKey] ? current : {
      ...current,
      [receiptKey]: Object.fromEntries(detail.candidateLinks.map((link, index) => [index, link.resolutionStatus !== "unresolved"])),
    });
  }, [receiptKey, detail]);

  const resolveLink = async (index: number) => {
    if (!receiptId || !onResolveArticleLink) return;
    const requestReceiptId = receiptId;
    const actionKey = `resolve:${requestReceiptId}:${index}`;
    if (!beginEmailSubmissionAction(inFlightActions.current, actionKey)) return;
    setBusyIndexByReceipt((current) => ({ ...current, [requestReceiptId]: index }));
    setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: "" }));
    try {
      const result = await onResolveArticleLink(requestReceiptId, index);
      if (!isCurrentEmailSubmissionAction(activeReceiptId.current, requestReceiptId)) return;
      if (!("url" in result)) {
        const reason = "reason" in result && typeof result.reason === "string"
          && /^(?:redirect_[a-z_]+|resolution_record_invalid|resolution_not_recorded)$/.test(result.reason)
          ? ` (${result.reason})` : "";
        setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: `The article destination could not be resolved safely${reason}. The original link remains private and unchanged.` }));
        return;
      }
      const candidate = detail && "submission" in detail ? detail.candidateLinks[index] : null;
      setResolvedByReceipt((current) => ({ ...current, [requestReceiptId]: { ...current[requestReceiptId], [index]: { url: result.url, title: result.title || candidate?.title || "Article" } } }));
      setSelectedByReceipt((current) => ({ ...current, [requestReceiptId]: { ...current[requestReceiptId], [index]: true } }));
      setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: "Resolved. This request may be recorded as a click by the newsletter sender." }));
    } catch {
      if (isCurrentEmailSubmissionAction(activeReceiptId.current, requestReceiptId)) {
        setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: "The article destination could not be resolved. Try again later." }));
      }
    } finally {
      endEmailSubmissionAction(inFlightActions.current, actionKey);
      setBusyIndexByReceipt((current) => ({ ...current, [requestReceiptId]: null }));
    }
  };

  const importSelected = async () => {
    if (!receiptId || !detail || !("submission" in detail) || !onImportCandidates) return;
    const requestReceiptId = receiptId;
    const actionKey = `import:${requestReceiptId}`;
    if (inFlightActions.current.has(actionKey)) return;
    const candidates = detail.candidateLinks.flatMap((link, index) => {
      if (!selected[index]) return [];
      const resolvedLink = resolved[index];
      if (!resolvedLink && link.resolutionStatus === "unresolved") return [];
      const url = resolvedLink?.url ?? link.url;
      return [{ candidateIndex: index, source_uri: url }];
    });
    if (!candidates.length) {
      setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: "Select at least one available candidate link. Resolve tracking links before importing them." }));
      return;
    }
    if (!beginEmailSubmissionAction(inFlightActions.current, actionKey)) return;
    setBusyImportByReceipt((current) => ({ ...current, [requestReceiptId]: true }));
    setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: "" }));
    try {
      const result = await onImportCandidates(requestReceiptId, candidates);
      if (!isCurrentEmailSubmissionAction(activeReceiptId.current, requestReceiptId)) return;
      setImportedByReceipt((current) => ({ ...current, [requestReceiptId]: result.references }));
      if (result.error) {
        setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: `${result.imported} of ${candidates.length} selected candidates were registered or matched. ${result.error}` }));
      } else {
        setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: `${result.imported} selected candidates are available as References. Predictions are queued in the cloud; review them when ready. Import does not approve or publish them.` }));
      }
    } catch {
      if (isCurrentEmailSubmissionAction(activeReceiptId.current, requestReceiptId)) {
        setNoticeByReceipt((current) => ({ ...current, [requestReceiptId]: "The import stopped. Any completed references are safe to retry; no review decision was made." }));
      }
    } finally {
      endEmailSubmissionAction(inFlightActions.current, actionKey);
      setBusyImportByReceipt((current) => ({ ...current, [requestReceiptId]: false }));
    }
  };

  return (
    <article className="news-desk-doctrine-card" data-monitoring-section="email-submissions">
      <div className="news-desk-doctrine-card__header"><div><h3>Email submissions</h3><span>Untrusted source material held privately for editor review</span></div></div>
      {items.length ? <ul className="news-desk-monitoring__list">
        {items.map((item) => <li key={item.receiptId} data-email-submission={item.receiptId}>
          <strong>{item.subject || "(no subject)"}</strong>
          <span>{formatUtc(item.observedAt)} · {item.linkCount} candidate links · {item.reviewRequired
            ? `${item.linkCount} await editor import` : `${item.processedCount} queued`}</span>
          {item.reviewRequired ? <span>Authentication warnings: private review required; nothing was routed automatically.</span> : null}
          {item.unresolvedLinkCount ? <span>{item.unresolvedLinkCount} tracking links remain unresolved and were not opened.</span> : null}
          <span>Envelope sender: {item.envelopeSender || "unknown"} · MIME From (unverified): {item.headerFrom || "unknown"}</span>
          <span>SES signals — SPF {item.verdicts.spf}, DKIM {item.verdicts.dkim}, DMARC {item.verdicts.dmarc}; spam {item.verdicts.spam}, virus {item.verdicts.virus}</span>
          {item.warnings.length ? <span>Warnings: {item.warnings.join(", ")}</span> : null}
          {item.errorCode ? <span>State: {item.status} ({item.errorCode})</span> : <span>State: {item.status}</span>}
          {onOpen ? <button type="button" onClick={() => onOpen(item.receiptId)}>Read email and review candidate links</button> : null}
        </li>)}
      </ul> : <p>No email submissions are available for this publication.</p>}
      {detail && "submission" in detail ? (
        <section aria-label="Email submission details" data-email-submission-details={detail.submission.receiptId}>
          <h4>{detail.submission.subject || "Submitted email"}</h4>
          <p>Original content is shown as inert text. Sender and message content are untrusted; no instructions are executed.</p>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{detail.safeBodyText}</pre>
          <h5>Candidate references ({detail.candidateLinks.length})</h5>
          <ul>{detail.candidateLinks.map((link, index) => <li key={`${link.url}-${index}`}>
            {link.resolutionStatus === "unresolved" && !resolved[index]
              ? <span>{link.title || "Newsletter article link"} (tracking redirect not opened)</span>
              : <a href={(resolved[index]?.url ?? link.url)} target="_blank" rel="noreferrer noopener">{resolved[index]?.title ?? (link.title || "Source link")}</a>}
            <label>
              <input type="checkbox" checked={selected[index] ?? false}
                disabled={link.resolutionStatus === "unresolved" && !resolved[index]}
                onChange={(event) => setSelectedByReceipt((current) => ({ ...current, [receiptKey]: { ...current[receiptKey], [index]: event.target.checked } }))} />
              Add as pending Reference
            </label>
            {link.resolutionStatus === "unresolved" && !resolved[index] ? (
              <button type="button" disabled={busyIndex !== null || !onResolveArticleLink} onClick={() => void resolveLink(index)}>
                {busyIndex === index ? "Resolving…" : "Resolve article redirect (may register a click)"}
              </button>
            ) : null}
          </li>)}</ul>
          <p>Adding links creates or reuses pending References. It does not approve, label, classify, or publish them.</p>
          <button type="button" disabled={busyImport || !onImportCandidates || !detail.submission.corpusId}
            onClick={() => void importSelected()}>
            {busyImport ? "Adding References…" : "Add selected links to References"}
          </button>
          {notice ? <p role="status" data-email-import-result>{notice}</p> : null}
          {importedReferences.length ? <ul>{importedReferences.map((reference, index) => (
            <li key={`${reference.id}-${index}`}><Link href={getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(reference.lineageId)}`, false)}>Review imported Reference {index + 1}</Link></li>
          ))}</ul> : null}
        </section>
      ) : detail && "error" in detail ? <p role="alert">You cannot read this submission.</p>
        : detail && "state" in detail ? <p role="alert">Submission details are unavailable.</p> : null}
    </article>
  );
}

function Ready({ data, demo, emailDetail, onEmailOpen, onResolveArticleLink, onImportCandidates }: {
  data: MonitoringOverview; demo: boolean; emailDetail: MonitoringEmailDetails | null; onEmailOpen: (id: string) => void;
  onResolveArticleLink?: (receiptId: string, candidateIndex: number) => Promise<MonitoringEmailArticleResolution>;
  onImportCandidates?: (receiptId: string, items: EmailReferenceImportItem[]) => Promise<EmailReferenceImportOutcome>;
}) {
  const router = data.router;
  return (
    <>
      {data.notice === "publication_not_routed" ? (
        <p className="news-desk-delegation-note" data-monitoring-notice>This publication is not one of the router&apos;s outputs, so no relevance is shown for it here.</p>
      ) : null}

      <EmailSubmissions items={data.emailSubmissions ?? []} detail={emailDetail} onOpen={onEmailOpen}
        onResolveArticleLink={demo ? undefined : onResolveArticleLink}
        onImportCandidates={demo ? undefined : onImportCandidates} />

      <article className="news-desk-doctrine-card" data-monitoring-section="router">
        <div className="news-desk-doctrine-card__header"><div><h3>Router</h3><span>Sends collected items to the shared Cyclotron and delivers relevant ones to References</span></div></div>
        {router ? (
          <p data-monitoring-router>
            <strong>{router.mode === "live" ? "Live" : "Dry run"}</strong>
            {router.mode === "live" ? " · decisions are made and delivered" : " · requests are checked but nothing is sent"}
            {" · "}{router.feedback ? "Feedback on" : "Feedback off"}
            {router.enabled ? "" : " · Paused"}
          </p>
        ) : <p>The router has not been configured.</p>}
      </article>

      <article className="news-desk-doctrine-card" data-monitoring-section="usage">
        <div className="news-desk-doctrine-card__header"><div><h3>Usage</h3><span>Observed router decisions, not a Cyclotron quota (UTC days)</span></div></div>
        {data.usage ? (
          <>
            <dl className="news-desk-monitoring__usage">
              <div><dt>Decisions today ({data.usage.day})</dt><dd>{data.usage.historyComplete ? data.usage.decisionsToday : `At least ${data.usage.decisionsToday}`}</dd></div>
              <div><dt>Decisions in inspected history</dt><dd>{data.usage.historyComplete ? data.usage.decisionsTotal : `At least ${data.usage.decisionsTotal}`}</dd></div>
            </dl>
            {!data.usage.historyComplete ? <p className="news-desk-delegation-note">Counts are lower bounds from a bounded history read.</p> : null}
          </>
        ) : <p>No usage recorded yet.</p>}
      </article>

      <article className="news-desk-doctrine-card" data-monitoring-section="feeds">
        <div className="news-desk-doctrine-card__header"><div><h3>Feeds watched</h3><span>What the collector reads</span></div></div>
        {data.feeds.length ? (
          <ul className="news-desk-monitoring__list">
            {data.feeds.map((feed) => (
              <li key={feed.id} data-monitoring-feed={feed.id}>
                <div>
                  <strong>{feed.id}</strong>
                  <span>{feedHost(feed.sourceUrl)}</span>
                </div>
                <span>{feed.enabled ? "Enabled" : "Disabled"} &middot; {everyText(feed.intervalSeconds)}{feed.limit ? ` · up to ${feed.limit} items` : ""}</span>
                <span>Last run {formatUtc(feed.lastFinishedAt)}{feed.lastStatus ? ` (${status(feed.lastStatus)})` : ""} &middot; next {formatUtc(feed.nextDueAt)}</span>
              </li>
            ))}
          </ul>
        ) : <p>No feed is configured.</p>}
      </article>

      <article className="news-desk-doctrine-card" data-monitoring-section="runs">
        <div className="news-desk-doctrine-card__header"><div><h3>Recent runs</h3><span>Collector receipts, newest first</span></div></div>
        {data.runs.length ? (
          <ul className="news-desk-monitoring__list">
            {data.runs.map((run) => (
              <li key={run.runId} data-monitoring-run={run.runId}>
                <strong>{formatUtc(run.startedAt)}</strong>
                <span>{status(run.status)}</span>
                <span>{run.new} new &middot; {run.revised} revised &middot; {run.unchanged} unchanged &middot; {run.errorCount} {run.errorCount === 1 ? "error" : "errors"}{run.errors.length ? ` (${run.errors.join("; ")})` : ""}</span>
              </li>
            ))}
          </ul>
        ) : <p>No collector runs recorded yet.</p>}
        {data.routerRuns.length ? (
          <ul className="news-desk-monitoring__list" data-monitoring-router-runs>
            {data.routerRuns.map((run) => (
              <li key={run.runId} data-monitoring-router-run={run.runId}>
                <strong>{formatUtc(run.startedAt)}</strong>
                <span>Router, {run.mode === "live" ? "live" : "dry run"}: {status(run.status)}{run.stoppedBy ? `, ${STOP_WORDS[run.stoppedBy] ?? run.stoppedBy}` : ""}</span>
                <span>{run.counts.examined ?? 0} examined &middot; {run.counts.decided ?? 0} judged &middot; {run.counts.delivered ?? 0} delivered &middot; {run.counts.deliveryFailed ?? 0} {(run.counts.deliveryFailed ?? 0) === 1 ? "delivery failure" : "delivery failures"} &middot; {run.errorCount} {run.errorCount === 1 ? "error" : "errors"}</span>
                {run.waitingForClassifier?.length ? <span data-monitoring-waiting-for-classifier>Waiting for classifier: {run.waitingForClassifier.join(", ")} (skipped, not an error; probed on a 30 minute to 6 hour backoff)</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </article>

      <article className="news-desk-doctrine-card" data-monitoring-section="queue">
        <div className="news-desk-doctrine-card__header"><div><h3>Collected queue</h3><span>Newest first, with what the shared Cyclotron decided</span></div></div>
        {data.items.length ? (
          <ul className="news-desk-monitoring__queue">
            {data.items.map((item) => <QueueItem key={`${item.monitorId ?? ""}-${item.sourceId}-${item.revision}`} item={item} ownId={data.scope.publicationId} demo={demo} />)}
          </ul>
        ) : <p>No items in the queue.</p>}
        {data.hiddenNotRelevant > 0 ? (
          <p className="news-desk-delegation-note" data-monitoring-hidden>
            {data.hiddenNotRelevant} {data.hiddenNotRelevant === 1 ? "item" : "items"} judged not relevant to this publication {data.hiddenNotRelevant === 1 ? "is" : "are"} not listed.
          </p>
        ) : null}
      </article>

      {data.otherMonitors?.length ? (
        <details className="news-desk-delegation-note" data-monitoring-other-monitors>
          <summary>Not routed to this site ({data.otherMonitors.length})</summary>
          <p>These monitors collect items, but none of them is routed to this site, so their items are not shown here.</p>
          <ul>{data.otherMonitors.map((id) => <li key={id} data-monitoring-other-monitor={id}>{id}</li>)}</ul>
        </details>
      ) : null}
    </>
  );
}

/** Presentation only: the panel fetches, this renders any result, so every state is testable from fixtures. */
export function MonitoringOverviewView({
  result,
  canViewAll,
  mode,
  onModeChange,
  demo = false,
  emailDetail = null,
  onEmailOpen = () => {},
  onResolveArticleLink,
  onImportCandidates,
}: {
  result: MonitoringResult | null;
  canViewAll: boolean;
  mode: MonitoringMode;
  onModeChange: (mode: MonitoringMode) => void;
  demo?: boolean;
  emailDetail?: MonitoringEmailDetails | null;
  onEmailOpen?: (receiptId: string) => void;
  onResolveArticleLink?: (receiptId: string, candidateIndex: number) => Promise<MonitoringEmailArticleResolution>;
  onImportCandidates?: (receiptId: string, items: EmailReferenceImportItem[]) => Promise<EmailReferenceImportOutcome>;
}) {
  let body: React.ReactNode;
  if (result === null) {
    body = <Message kind="loading" title="Loading monitoring" />;
  } else if ("error" in result) {
    body = result.error === "forbidden"
      ? <Message kind="forbidden" title="Monitoring is for editors and admins">Your account does not have access to this page. Ask an admin for the editor role.</Message>
      : <Message kind="error" title="Monitoring could not be read">The request was not understood. Reload the page.</Message>;
  } else if (result.state === "not_configured") {
    body = <Message kind="not-configured" title="Monitoring is not set up for this publication">The monitoring pipeline is not connected to this site&apos;s account, so there is nothing to show.</Message>;
  } else if (result.state === "unavailable") {
    body = <Message kind="unavailable" title="Monitoring could not be read right now">The pipeline is not affected. Try again in a minute.</Message>;
  } else if (result.state === "empty") {
    body = <Message kind="empty" title="Nothing has been collected yet">No feed is configured and no run has been recorded. Items appear here after the collector&apos;s first run.</Message>;
  } else {
    body = <Ready data={result} demo={demo} emailDetail={emailDetail} onEmailOpen={onEmailOpen}
      onResolveArticleLink={onResolveArticleLink} onImportCandidates={onImportCandidates} />;
  }
  const scopeLine = result && "scope" in result
    ? (result.scope.mode === "all" ? "Showing the whole shared pipeline, every publication." : `Showing what is relevant to ${result.scope.publicationId ?? "this publication"}.`)
    : null;
  return (
    <div data-news-desk-admin-panel="monitoring">
      <article className="news-desk-doctrine-card">
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Monitoring</h3>
            <span>The automated research pipeline: collection, judging and delivery to References. Read only.</span>
          </div>
        </div>
        {canViewAll ? (
          <div className="news-desk-monitoring__scope" role="group" aria-label="Scope">
            <button type="button" aria-pressed={mode === "publication"} data-monitoring-scope="publication" onClick={() => onModeChange("publication")}>This publication</button>
            <button type="button" aria-pressed={mode === "all"} data-monitoring-scope="all" onClick={() => onModeChange("all")}>Whole shared pipeline</button>
          </div>
        ) : null}
        {scopeLine ? <p className="news-desk-delegation-note" data-monitoring-scope-line>{scopeLine} {result && "asOf" in result ? `As of ${formatUtc(result.asOf)}.` : ""}</p> : null}
      </article>
      {body}
    </div>
  );
}
