import {
  countsText,
  formatInZone,
  formatUtc,
  issueEditorHref,
  statusLabel,
  statusMark,
  type NewsletterDelivery,
  type NewsletterEvent,
  type NewsletterIssue,
  type NewsletterOverview,
  type NewsletterSubscriber,
} from "../lib/newsletter-model";

/** Presentation only: the panel fetches and holds state, these render what they are given, so every state is testable from fixtures. */

export function ListsCard({ overview }: { overview: NewsletterOverview }) {
  const { totals } = overview;
  return (
    <article className="news-desk-doctrine-card" data-newsletter-section="lists">
      <div className="news-desk-doctrine-card__header">
        <div><h3>Lists</h3><span>Subscribers per list. A person on two lists counts on each.</span></div>
      </div>
      {overview.lists.length ? (
        <dl className="news-desk-monitoring__usage">
          {overview.lists.map((list) => (
            <div key={list.id} data-newsletter-list={list.id}>
              <dt>{list.name} ({list.kind === "roundup" ? "roundup" : list.kind === "alert" ? "alerts" : list.kind})</dt>
              <dd>{list.confirmed}</dd>
              <span className="news-desk-newsletter__quiet">confirmed &middot; {list.pending} pending &middot; {list.unsubscribed} unsubscribed</span>
            </div>
          ))}
        </dl>
      ) : <p>No list is configured.</p>}
      <p className="news-desk-delegation-note" data-newsletter-totals>
        Across the site: {totals.confirmed} confirmed, {totals.pending} waiting to confirm, {totals.unsubscribed} unsubscribed.
        {" "}{overview.suppressed} {overview.suppressed === 1 ? "address is" : "addresses are"} suppressed after a bounce or complaint.
      </p>
    </article>
  );
}

export function SiteStatusCard({ paused, isAdmin, busy, onResume }: { paused: NewsletterOverview["paused"]; isAdmin: boolean; busy: boolean; onResume: () => void }) {
  return (
    <article className="news-desk-doctrine-card" data-newsletter-section="site-status">
      <div className="news-desk-doctrine-card__header">
        <div><h3>Site status</h3><span>Sending turns itself off when bounces or complaints run high</span></div>
      </div>
      {paused.paused ? (
        <div className="category-steering-alert" role="alert" data-newsletter-paused>
          <strong><span aria-hidden="true">■ </span>Sending is paused.</strong>{" "}
          {paused.reason ? <>Reason: {paused.reason}. </> : null}
          {paused.pausedAt ? <>Paused {formatUtc(paused.pausedAt)}. </> : null}
          Issues due now are blocked until sending resumes; approve a blocked issue again afterwards.
          <div className="news-desk-doctrine-card__actions">
            {isAdmin ? (
              <button type="button" disabled={busy} data-newsletter-resume onClick={onResume}>Resume sending</button>
            ) : <span>An admin can resume sending.</span>}
          </div>
        </div>
      ) : (
        <p data-newsletter-running><span aria-hidden="true">✓ </span>Sending is on.{paused.resumedAt ? ` Resumed ${formatUtc(paused.resumedAt)}.` : ""}</p>
      )}
    </article>
  );
}

/** What an issue row says about the issue; the buttons beside it belong to the panel. */
export function IssueSummary({ issue, zone, demo }: { issue: NewsletterIssue; zone: string; demo: boolean }) {
  return (
    <>
      <header>
        <strong>{issue.subject || "(no subject)"}</strong>
        <span data-newsletter-status={issue.status}><span aria-hidden="true">{statusMark(issue.status)} </span>{statusLabel(issue.status)}</span>
      </header>
      <p>{issue.listName ?? issue.listId}{issue.kind ? ` · ${issue.kind}` : ""}</p>
      {issue.sendAt ? (
        <p data-newsletter-send-at>
          {issue.status === "sent" || issue.status === "sending" ? "Scheduled for " : "Send at "}
          <time dateTime={issue.sendAt} title={formatUtc(issue.sendAt)}>{formatInZone(issue.sendAt, zone)}</time>
          {issue.approvedBy ? ` · approved by ${issue.approvedBy}` : ""}
        </p>
      ) : null}
      <p data-newsletter-counts>{countsText(issue.counts ?? {})}</p>
      {issue.status === "blocked" ? (
        <p className="category-steering-alert" data-newsletter-blocked>
          Blocked: {issue.note ?? "see the issue"}. Fix the cause, then approve it again.
        </p>
      ) : issue.note ? <p data-newsletter-note>Note: {issue.note}</p> : null}
      {issue.editedSinceApproval ? (
        <p className="category-steering-alert" data-newsletter-edited>
          Edited since approval. When it comes due it will go back to draft and send nothing. Approve it again to send this version.
        </p>
      ) : null}
      <p className="news-desk-newsletter__links">
        {issue.itemId ? <a href={issueEditorHref(issue.itemId, demo)} data-newsletter-editor-link>Open in the editor</a> : <span>No item</span>}
        {issue.archiveUrl ? <> &middot; <a href={issue.archiveUrl} target="_blank" rel="noreferrer noopener" data-newsletter-archive-link>Archive page</a></> : null}
      </p>
    </>
  );
}

export function DeliveriesCard({
  issue, rows, events, hasMore, loading, isAdmin, onMore,
}: {
  issue: NewsletterIssue; rows: NewsletterDelivery[]; events: NewsletterEvent[]; hasMore: boolean; loading: boolean; isAdmin: boolean; onMore: () => void;
}) {
  return (
    <article className="news-desk-doctrine-card" data-newsletter-section="deliveries" data-newsletter-deliveries-for={issue.issueId}>
      <div className="news-desk-doctrine-card__header">
        <div><h3>Delivery history</h3><span>{issue.subject} &middot; {countsText(issue.counts ?? {})}</span></div>
      </div>
      {!isAdmin ? <p className="news-desk-delegation-note">Addresses are masked for editors.</p> : null}
      {rows.length ? (
        <table className="news-desk-newsletter__table">
          <thead><tr><th scope="col">Address</th><th scope="col">Result</th><th scope="col">Queued (UTC)</th><th scope="col">Last event (UTC)</th></tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.address}-${index}`} data-newsletter-delivery={row.status}>
                <td>{row.address}</td>
                <td>{row.status}{row.error ? ` (${row.error})` : ""}</td>
                <td>{formatUtc(row.at)}</td>
                <td>{row.eventAt ? formatUtc(row.eventAt) : "none yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p>{loading ? "Loading deliveries..." : "Nothing has been sent for this issue."}</p>}
      {hasMore ? <div className="news-desk-doctrine-card__actions"><button type="button" disabled={loading} onClick={onMore}>Load more deliveries</button></div> : null}
      <h4>Recent events for this issue</h4>
      {events.length ? (
        <ul className="news-desk-monitoring__list" data-newsletter-events>
          {events.map((event, index) => (
            <li key={`${event.at}-${index}`}>
              <strong>{event.type}{event.detail ? ` (${event.detail})` : ""}</strong>
              <span>{event.list ?? ""}</span>
              <span>{formatUtc(event.at)}</span>
            </li>
          ))}
        </ul>
      ) : <p>No recent events for this issue. Events are kept for 90 days and the panel shows the latest 100 for the whole site.</p>}
    </article>
  );
}

export function SubscribersTable({ rows, zone }: { rows: NewsletterSubscriber[]; zone: string }) {
  return (
    <table className="news-desk-newsletter__table" data-newsletter-subscribers>
      <thead><tr><th scope="col">Address</th><th scope="col">Status</th><th scope="col">Lists</th><th scope="col">Signed up</th><th scope="col">Confirmed</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.email} data-newsletter-subscriber={row.status}>
            <td>{row.email}</td>
            <td>{row.status}</td>
            <td>{row.lists.length ? row.lists.map((entry) => `${entry.id} (${entry.status})`).join(", ") : "none"}</td>
            <td>{formatInZone(row.createdAt, zone)}</td>
            <td>{row.confirmedAt ? formatInZone(row.confirmedAt, zone) : "not yet"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
