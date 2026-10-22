"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { callNewsletter, type NewsletterApi } from "../lib/newsletter-client";
import { createFixtureApi } from "../lib/newsletter-fixture";
import {
  ISSUE_STATUS_FILTERS,
  canApprove,
  canCancel,
  canStop,
  failureText,
  formatInZone,
  isoToZonedInput,
  nextWholeHourInput,
  statusLabel,
  subscribersToCsv,
  validTimeZone,
  zonedInputToIso,
  type NewsletterDelivery,
  type NewsletterExportRow,
  type NewsletterFailure,
  type NewsletterIssue,
  type NewsletterOverview,
  type NewsletterPreview,
  type NewsletterSubscriber,
} from "../lib/newsletter-model";
import { DeliveriesCard, IssueSummary, ListsCard, SiteStatusCard, SubscribersTable } from "./newsletter-sections";

type Message = { kind: "ok" | "problem"; text: string } | null;
type Drawer = { issueId: string; mode: "preview" | "approve" | "stop" | "cancel" } | null;
type Result<T> = ({ ok: true } & T) | NewsletterFailure;

const isFailure = (value: { ok: boolean }): value is NewsletterFailure => value.ok === false;

/**
 * Administration, Newsletter: subscriber counts, issues with their actions, delivery history, the pause, and (for admins) the
 * subscriber list, CSV export and erasure. It never subscribes to anything live: it refreshes after each action and on the Refresh button.
 */
export function NewsletterPanel({ isAdmin, isDemo }: { isAdmin: boolean; isDemo: boolean }) {
  const api: NewsletterApi = useMemo(() => (isDemo ? createFixtureApi({ admin: isAdmin }) : callNewsletter), [isDemo, isAdmin]);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const [overview, setOverview] = useState<NewsletterOverview | null>(null);
  const [issues, setIssues] = useState<NewsletterIssue[] | null>(null);
  const [edited, setEdited] = useState<Record<string, boolean>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [preview, setPreview] = useState<Result<NewsletterPreview> | null>(null);
  const [approveAt, setApproveAt] = useState("");
  const [deliveriesFor, setDeliveriesFor] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<NewsletterDelivery[]>([]);
  const [deliveriesCursor, setDeliveriesCursor] = useState<string | null>(null);
  const [deliveriesLoading, setDeliveriesLoading] = useState(false);
  const [subscribers, setSubscribers] = useState<NewsletterSubscriber[] | null>(null);
  const [subscribersCursor, setSubscribersCursor] = useState<string | null>(null);
  const [listFilter, setListFilter] = useState("");
  const [subscriberStatus, setSubscriberStatus] = useState("");
  const [eraseEmail, setEraseEmail] = useState("");
  const [eraseConfirm, setEraseConfirm] = useState(false);

  const zone = useMemo(() => {
    const roundup = overview?.lists.find((list) => list.timezone)?.timezone;
    return validTimeZone(roundup) ?? validTimeZone(Intl.DateTimeFormat().resolvedOptions().timeZone) ?? "UTC";
  }, [overview]);

  const loadOverview = useCallback(async () => {
    const result = (await api("newsletterOverview")) as Result<NewsletterOverview>;
    if (!live.current) return;
    if (isFailure(result)) {
      setProblem(result.error === "forbidden" ? "forbidden" : failureText(result));
      return;
    }
    setProblem(null);
    setOverview(result);
  }, [api]);

  const loadIssues = useCallback(async () => {
    const result = (await api("newsletterIssues", { limit: 100, ...(statusFilter ? { status: statusFilter } : {}) })) as Result<{ issues: NewsletterIssue[] }>;
    if (!live.current) return;
    if (isFailure(result)) {
      setMessage({ kind: "problem", text: failureText(result) });
      return;
    }
    setIssues(result.issues);
    // The list does not say whether an approved issue was edited; the single-issue read does. Scheduled issues are few.
    const scheduled = result.issues.filter((issue) => issue.status === "scheduled").slice(0, 10);
    const checks = await Promise.all(scheduled.map(async (issue) => [issue.issueId, await api("newsletterIssue", { issueId: issue.issueId })] as const));
    if (!live.current) return;
    setEdited(Object.fromEntries(checks.map(([id, one]) => [id, !isFailure(one as Result<object>) && Boolean((one as { issue?: NewsletterIssue }).issue?.editedSinceApproval)])));
  }, [api, statusFilter]);

  const loadSubscribers = useCallback(
    async (cursor?: string | null) => {
      if (!isAdmin) return;
      const result = (await api("newsletterSubscribers", {
        ...(listFilter ? { listId: listFilter } : {}),
        ...(subscriberStatus ? { status: subscriberStatus } : {}),
        ...(cursor ? { cursor } : {}),
      })) as Result<{ subscribers: NewsletterSubscriber[]; cursor?: string }>;
      if (!live.current) return;
      if (isFailure(result)) {
        setMessage({ kind: "problem", text: failureText(result) });
        return;
      }
      setSubscribers((current) => (cursor && current ? [...current, ...result.subscribers] : result.subscribers));
      setSubscribersCursor(result.cursor ?? null);
    },
    [api, isAdmin, listFilter, subscriberStatus],
  );

  const loadDeliveries = useCallback(
    async (issueId: string, cursor?: string | null) => {
      setDeliveriesLoading(true);
      const result = (await api("newsletterIssueDeliveries", { issueId, ...(cursor ? { cursor } : {}) })) as Result<{ deliveries: NewsletterDelivery[]; cursor?: string }>;
      if (!live.current) return;
      setDeliveriesLoading(false);
      if (isFailure(result)) {
        setMessage({ kind: "problem", text: failureText(result) });
        return;
      }
      setDeliveries((current) => (cursor ? [...current, ...result.deliveries] : result.deliveries));
      setDeliveriesCursor(result.cursor ?? null);
    },
    [api],
  );

  const refresh = useCallback(async () => {
    await Promise.all([loadOverview(), loadIssues(), loadSubscribers()]);
    if (deliveriesFor) await loadDeliveries(deliveriesFor);
  }, [loadOverview, loadIssues, loadSubscribers, loadDeliveries, deliveriesFor]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);
  useEffect(() => {
    void loadIssues();
  }, [loadIssues]);
  useEffect(() => {
    setSubscribers(null);
    void loadSubscribers();
  }, [loadSubscribers]);

  /** Runs an operation with the buttons disabled, says what happened, then reloads what it may have changed. */
  const act = async (key: string, run: () => Promise<{ text: string } | NewsletterFailure>, reload: Array<"overview" | "issues" | "subscribers"> = ["overview", "issues"]) => {
    setBusy(key);
    setMessage(null);
    try {
      const outcome = await run();
      if (!live.current) return;
      if ("ok" in outcome) {
        setMessage({ kind: "problem", text: failureText(outcome) });
      } else {
        setMessage({ kind: "ok", text: outcome.text });
        await Promise.all([
          reload.includes("overview") ? loadOverview() : null,
          reload.includes("issues") ? loadIssues() : null,
          reload.includes("subscribers") ? loadSubscribers() : null,
          deliveriesFor ? loadDeliveries(deliveriesFor) : null,
        ]);
      }
    } finally {
      if (live.current) setBusy(null);
    }
  };

  const openPreview = async (issue: NewsletterIssue) => {
    if (drawer?.issueId === issue.issueId && drawer.mode === "preview") {
      setDrawer(null);
      return;
    }
    setDrawer({ issueId: issue.issueId, mode: "preview" });
    setPreview(null);
    const result = (await api("newsletterPreview", { issueId: issue.issueId })) as Result<NewsletterPreview>;
    if (live.current) setPreview(result);
  };

  const openApprove = (issue: NewsletterIssue) => {
    setApproveAt(issue.sendAt ? isoToZonedInput(issue.sendAt, zone) : nextWholeHourInput(new Date(), zone));
    setDrawer({ issueId: issue.issueId, mode: "approve" });
  };

  const approve = (issue: NewsletterIssue) => {
    const sendAt = zonedInputToIso(approveAt, zone);
    if (!sendAt) {
      setMessage({ kind: "problem", text: "Choose a date and time." });
      return;
    }
    void act(`approve:${issue.issueId}`, async () => {
      const result = (await api("newsletterApproveIssue", { issueId: issue.issueId, sendAt })) as Result<{ issue: NewsletterIssue; adjusted?: boolean; warnings?: string[] }>;
      if (isFailure(result)) return result;
      setDrawer(null);
      const when = formatInZone(result.issue.sendAt, zone);
      const extras = [result.adjusted ? "That was too soon, so it was moved a couple of minutes ahead." : "", ...(result.warnings ?? [])].filter(Boolean);
      return { text: `Approved for ${when}.${extras.length ? ` ${extras.join(" ")}` : ""}` };
    });
  };

  const simple = (issue: NewsletterIssue, operation: "newsletterCancelIssue" | "newsletterStopIssue", done: string) => {
    void act(`${operation}:${issue.issueId}`, async () => {
      const result = (await api(operation, { issueId: issue.issueId })) as Result<object>;
      if (isFailure(result)) return result;
      setDrawer(null);
      return { text: done };
    });
  };

  const testSend = (issue: NewsletterIssue) =>
    void act(`test:${issue.issueId}`, async () => {
      const result = (await api("newsletterTestSend", { issueId: issue.issueId })) as Result<object>;
      return isFailure(result) ? result : { text: "Test sent to your address." };
    }, []);

  const newDraft = (listId: string) =>
    void act(`draft:${listId}`, async () => {
      const result = (await api("newsletterCreateDraft", { listId })) as Result<{ status?: string; items?: number }>;
      if (isFailure(result)) return result;
      if (result.status === "created") return { text: `Draft created with ${result.items ?? 0} ${result.items === 1 ? "item" : "items"}. Open it in the editor to write the introduction.` };
      if (result.status === "exists") return { text: "This week already has a draft for that list." };
      return { text: "Nothing has been published since the last issue, so no draft was made." };
    });

  const showDeliveries = (issue: NewsletterIssue) => {
    setDeliveriesFor(issue.issueId);
    setDeliveries([]);
    setDeliveriesCursor(null);
    void loadDeliveries(issue.issueId);
  };

  const resume = () =>
    void act("resume", async () => {
      const result = (await api("newsletterResume")) as Result<object>;
      return isFailure(result) ? result : { text: "Sending resumed. Approve any blocked issue again." };
    });

  const exportCsv = () =>
    void act("export", async () => {
      const rows: NewsletterExportRow[] = [];
      let cursor: string | undefined;
      do {
        const result = (await api("newsletterExport", cursor ? { cursor } : {})) as Result<{ rows: NewsletterExportRow[]; cursor?: string }>;
        if (isFailure(result)) return result;
        rows.push(...result.rows);
        cursor = result.cursor;
      } while (cursor);
      const url = URL.createObjectURL(new Blob([subscribersToCsv(rows)], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "newsletter-subscribers.csv";
      link.click();
      URL.revokeObjectURL(url);
      return { text: `Exported ${rows.length} confirmed and pending ${rows.length === 1 ? "subscriber" : "subscribers"}.` };
    }, []);

  const erase = () =>
    void act("erase", async () => {
      const email = eraseEmail.trim().toLowerCase();
      const result = (await api("newsletterErase", { email })) as Result<{ removed: number }>;
      if (isFailure(result)) return result;
      setEraseEmail("");
      setEraseConfirm(false);
      return { text: `Erased ${email}: ${result.removed} ${result.removed === 1 ? "record" : "records"} removed.` };
    }, ["overview", "subscribers"]);

  if (problem === "forbidden") {
    return (
      <div data-news-desk-admin-panel="newsletter">
        <div className="category-steering-empty" role="alert" data-newsletter-state="forbidden">
          <strong>The newsletter is for editors and admins</strong>
          <p>Your account does not have access to this page. Ask an admin for the editor role.</p>
        </div>
      </div>
    );
  }

  const roundupLists = overview?.lists.filter((list) => list.kind === "roundup") ?? [];
  const deliveriesIssue = issues?.find((issue) => issue.issueId === deliveriesFor) ?? null;
  const loading = overview === null && !problem;

  return (
    <div data-news-desk-admin-panel="newsletter">
      <article className="news-desk-doctrine-card">
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Newsletter</h3>
            <span>Subscribers, issues and delivery for the site&apos;s email. {isAdmin ? "You are an admin: you can approve, stop and see addresses." : "You are an editor: you can preview and test, and see counts. An admin approves."}</span>
          </div>
        </div>
        <div className="news-desk-doctrine-card__actions">
          <button type="button" data-newsletter-refresh disabled={busy !== null} onClick={() => void refresh()}>Refresh</button>
        </div>
        <p role="status" aria-live="polite" data-newsletter-message data-kind={message?.kind ?? (loading ? "loading" : "idle")}>
          {message ? (message.kind === "problem" ? `Problem: ${message.text}` : message.text) : loading ? "Loading..." : problem ?? ""}
        </p>
      </article>

      {overview ? <ListsCard overview={overview} /> : null}
      {overview ? <SiteStatusCard paused={overview.paused} isAdmin={isAdmin} busy={busy !== null} onResume={resume} /> : null}

      <article className="news-desk-doctrine-card" data-newsletter-section="issues">
        <div className="news-desk-doctrine-card__header">
          <div><h3>Issues</h3><span>Newest first. Times are in {zone}; hover a time for UTC.</span></div>
        </div>
        <label className="news-desk-doctrine-card__field">
          <span>Show</span>
          <select value={statusFilter} data-newsletter-status-filter onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All issues</option>
            {ISSUE_STATUS_FILTERS.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
          </select>
        </label>
        {roundupLists.length ? (
          <div className="news-desk-doctrine-card__actions">
            {roundupLists.map((list) => (
              <button key={list.id} type="button" data-newsletter-new-draft={list.id} disabled={busy !== null} onClick={() => newDraft(list.id)}>New draft: {list.name}</button>
            ))}
          </div>
        ) : null}
        {issues === null ? <p>Loading issues...</p> : issues.length === 0 ? (
          <p data-newsletter-no-issues>{statusFilter ? `No ${statusLabel(statusFilter).toLowerCase()} issues.` : "No issues yet. A roundup draft appears on its schedule, or make one with New draft."}</p>
        ) : (
          <div className="news-desk-user-list">
            {issues.map((issue) => {
              const open = drawer?.issueId === issue.issueId ? drawer.mode : null;
              const row = { ...issue, editedSinceApproval: edited[issue.issueId] };
              return (
                <div className="news-desk-user-row" key={issue.issueId} data-newsletter-issue={issue.issueId} data-status={issue.status}>
                  <div><IssueSummary issue={row} zone={zone} demo={isDemo} /></div>
                  <div className="news-desk-user-row__actions">
                    <button type="button" data-newsletter-action="preview" aria-expanded={open === "preview"} onClick={() => void openPreview(issue)}>Preview</button>
                    <button type="button" data-newsletter-action="test" disabled={busy !== null} onClick={() => testSend(issue)}>Test send</button>
                    <button type="button" data-newsletter-action="deliveries" onClick={() => showDeliveries(issue)}>Deliveries</button>
                    {isAdmin && canApprove(issue.status) ? (
                      <button type="button" data-newsletter-action="approve" aria-expanded={open === "approve"} disabled={busy !== null} onClick={() => openApprove(issue)}>
                        {issue.status === "scheduled" ? "Change time" : "Approve for a time"}
                      </button>
                    ) : null}
                    {isAdmin && canCancel(issue.status) ? (
                      <button type="button" data-newsletter-action="cancel" disabled={busy !== null} onClick={() => simple(issue, "newsletterCancelIssue", "Cancelled. The issue is a draft again.")}>Cancel</button>
                    ) : null}
                    {isAdmin && canStop(issue.status) ? (
                      <button type="button" data-newsletter-action="stop" disabled={busy !== null} onClick={() => setDrawer({ issueId: issue.issueId, mode: "stop" })}>Stop</button>
                    ) : null}
                  </div>
                  {open === "preview" ? (
                    <div className="news-desk-newsletter__drawer" data-newsletter-preview>
                      {preview === null ? <p>Loading preview...</p> : isFailure(preview) ? (
                        <p className="category-steering-alert" role="alert">{failureText(preview)}</p>
                      ) : (
                        <>
                          <p className="news-desk-delegation-note">
                            Subject: <strong>{preview.subject}</strong> &middot; {Math.ceil(preview.bytes / 1024)} KB of HTML
                            {preview.bytes > 100 * 1024 ? " (Gmail clips messages over 102 KB)" : ""}
                          </p>
                          {!preview.postalAddress ? (
                            <p className="category-steering-alert" role="alert" data-newsletter-postal>{failureText({ ok: false, error: "postal_address_missing" })} The preview shows a placeholder.</p>
                          ) : null}
                          <iframe title={`Preview of ${issue.subject}`} sandbox="" srcDoc={preview.html} className="news-desk-newsletter__frame" />
                          <h4>Plain text version</h4>
                          <pre className="news-desk-newsletter__text">{preview.text}</pre>
                        </>
                      )}
                    </div>
                  ) : null}
                  {open === "approve" ? (
                    <div className="news-desk-newsletter__drawer" data-newsletter-approve>
                      <label className="news-desk-doctrine-card__field">
                        <span>Send at ({zone})</span>
                        <input type="datetime-local" value={approveAt} data-newsletter-send-at-input onChange={(event) => setApproveAt(event.target.value)} />
                      </label>
                      <p className="news-desk-delegation-note">This sends the issue as it is now. If it is edited before this time, it goes back to draft and sends nothing. A time less than two minutes ahead is moved to two minutes from now.</p>
                      <div className="news-desk-doctrine-card__actions">
                        <button type="button" data-newsletter-confirm-approve disabled={busy !== null} onClick={() => approve(issue)}>Approve for this time</button>
                        <button type="button" onClick={() => setDrawer(null)}>Keep as is</button>
                      </div>
                    </div>
                  ) : null}
                  {open === "stop" ? (
                    <div className="news-desk-newsletter__drawer" data-newsletter-stop>
                      <p className="category-steering-alert">Stop sending this issue? The addresses already mailed stay mailed; the rest are not sent. This cannot be resumed.</p>
                      <div className="news-desk-doctrine-card__actions">
                        <button type="button" data-newsletter-confirm-stop disabled={busy !== null} onClick={() => simple(issue, "newsletterStopIssue", "Stopped. No more of this issue will be sent.")}>Stop sending</button>
                        <button type="button" onClick={() => setDrawer(null)}>Keep sending</button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </article>

      {deliveriesIssue ? (
        <DeliveriesCard
          issue={deliveriesIssue}
          rows={deliveries}
          events={(overview?.events ?? []).filter((event) => event.issue === deliveriesIssue.issueId)}
          hasMore={deliveriesCursor !== null}
          loading={deliveriesLoading}
          isAdmin={isAdmin}
          onMore={() => void loadDeliveries(deliveriesIssue.issueId, deliveriesCursor)}
        />
      ) : (
        <article className="news-desk-doctrine-card" data-newsletter-section="deliveries">
          <div className="news-desk-doctrine-card__header"><div><h3>Delivery history</h3><span>Choose Deliveries on an issue to see who it went to and what happened</span></div></div>
        </article>
      )}

      <article className="news-desk-doctrine-card" data-newsletter-section="subscribers">
        <div className="news-desk-doctrine-card__header">
          <div><h3>Subscribers</h3><span>{isAdmin ? "Addresses are personal data. Only admins see them." : "Only admins see addresses."}</span></div>
        </div>
        {isAdmin ? (
          <>
            <div className="news-desk-newsletter__filters">
              <label className="news-desk-doctrine-card__field">
                <span>List</span>
                <select value={listFilter} data-newsletter-list-filter onChange={(event) => setListFilter(event.target.value)}>
                  <option value="">All lists</option>
                  {(overview?.lists ?? []).map((list) => <option key={list.id} value={list.id}>{list.name}</option>)}
                </select>
              </label>
              <label className="news-desk-doctrine-card__field">
                <span>Status</span>
                <select value={subscriberStatus} data-newsletter-subscriber-filter onChange={(event) => setSubscriberStatus(event.target.value)}>
                  <option value="">Any status</option>
                  <option value="confirmed">Confirmed</option>
                  <option value="pending">Waiting to confirm</option>
                  <option value="unsubscribed">Unsubscribed</option>
                </select>
              </label>
            </div>
            <div className="news-desk-doctrine-card__actions">
              <button type="button" data-newsletter-export disabled={busy !== null} onClick={exportCsv}>Export CSV (confirmed and pending)</button>
            </div>
            {subscribers === null ? <p>Loading subscribers...</p> : subscribers.length ? <SubscribersTable rows={subscribers} zone={zone} /> : <p>No subscribers match.</p>}
            {subscribersCursor ? (
              <div className="news-desk-doctrine-card__actions"><button type="button" data-newsletter-more-subscribers onClick={() => void loadSubscribers(subscribersCursor)}>Load more</button></div>
            ) : null}
            <div className="news-desk-merge-panel" data-newsletter-erase>
              <strong>Erase one subscriber</strong>
              <p className="news-desk-delegation-note">Removes the address, its list memberships, any suppression and its delivery records. Use it for a request to be forgotten. It cannot be undone.</p>
              <label className="news-desk-doctrine-card__field">
                <span>Address to erase</span>
                <input type="email" value={eraseEmail} autoComplete="off" data-newsletter-erase-input onChange={(event) => { setEraseEmail(event.target.value); setEraseConfirm(false); }} />
              </label>
              {eraseConfirm ? (
                <div className="news-desk-doctrine-card__actions">
                  <span>Erase {eraseEmail.trim()} for good?</span>
                  <button type="button" data-newsletter-confirm-erase disabled={busy !== null} onClick={erase}>Erase permanently</button>
                  <button type="button" onClick={() => setEraseConfirm(false)}>Keep</button>
                </div>
              ) : (
                <div className="news-desk-doctrine-card__actions">
                  <button type="button" data-newsletter-erase-button disabled={!eraseEmail.trim() || busy !== null} onClick={() => setEraseConfirm(true)}>Erase…</button>
                </div>
              )}
            </div>
          </>
        ) : (
          <p className="news-desk-delegation-note" data-newsletter-editor-note>You can see how many people are on each list above. The address list, export and erasure are for admins.</p>
        )}
      </article>
    </div>
  );
}
