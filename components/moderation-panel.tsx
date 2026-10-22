"use client";

import { generateClient } from "aws-amplify/data";
import amplifyOutputs from "papyrus-amplify-outputs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { pluginSettings, type PluginOutputs } from "../lib/plugin-settings";
import {
  buildActionLog,
  buildHidden,
  buildQueue,
  moderationModeText,
  receiptMessage,
  shortReader,
  type ActionEntry,
  type ActionRow,
  type CommentRow,
  type ModerationActionName,
  type ModerationRow,
  type ModerationTarget,
  type Receipt,
  type ReportRow,
  type SubmissionRow,
} from "../lib/reader-moderation";

const SUBMISSION_FIELDS = "id canonicalUrl domain title kind note readerId state moderation reportCount signals itemId createdAt";
const COMMENT_FIELDS = "id subjectKey readerId body parentId state moderation reportCount signals createdAt";

const QUEUE_SUBMISSIONS = `query Queue($nextToken: String) { listReaderSubmissionsByModerationAndCreatedAt(moderation: "new", sortDirection: DESC, limit: 100, nextToken: $nextToken) { items { ${SUBMISSION_FIELDS} } nextToken } }`;
const QUEUE_COMMENTS = `query Queue($nextToken: String) { listReaderCommentsByModerationAndCreatedAt(moderation: "new", sortDirection: DESC, limit: 100, nextToken: $nextToken) { items { ${COMMENT_FIELDS} } nextToken } }`;
const HIDDEN_SUBMISSIONS = `query Hidden($nextToken: String) { listReaderSubmissions(filter: { state: { eq: "hidden" } }, limit: 500, nextToken: $nextToken) { items { ${SUBMISSION_FIELDS} } nextToken } }`;
const HIDDEN_COMMENTS = `query Hidden($nextToken: String) { listReaderComments(filter: { state: { eq: "hidden" } }, limit: 500, nextToken: $nextToken) { items { ${COMMENT_FIELDS} } nextToken } }`;
const OPEN_REPORTS = `query Reports($nextToken: String) { listReaderReports(filter: { state: { eq: "open" } }, limit: 500, nextToken: $nextToken) { items { id targetType target reporterReaderId reason state createdAt } nextToken } }`;
const ACTIONS = `query Actions($nextToken: String) { listModerationActions(limit: 500, nextToken: $nextToken) { items { id by actorSub action targetType target reason fromState toState undoOf undoneBy at } nextToken } }`;
const HANDLES = `query Handles($nextToken: String) { listReaderHandles(limit: 1000, nextToken: $nextToken) { items { id readerId } nextToken } }`;
const MODERATE = `mutation Moderate($action: String!, $targetType: String!, $target: String!, $reason: String, $undoOf: String) { moderateReader(action: $action, targetType: $targetType, target: $target, reason: $reason, undoOf: $undoOf) { status id error message } }`;

type GraphResult = { data?: Record<string, { items: unknown[]; nextToken?: string | null } | Receipt | null>; errors?: { message?: string }[] };
const MAXIMUM_PAGES = 20;

async function loadAll<T>(query: string, field: string): Promise<T[]> {
  const client = generateClient({ authMode: "userPool" });
  const rows: T[] = [];
  let nextToken: string | null | undefined;
  for (let page = 0; page < MAXIMUM_PAGES; page += 1) {
    const result = (await client.graphql({ query, variables: { nextToken } })) as GraphResult;
    if (result.errors?.length) throw new Error(result.errors[0]?.message ?? "Could not load moderation data.");
    const connection = result.data?.[field] as { items: T[]; nextToken?: string | null } | undefined;
    rows.push(...(connection?.items ?? []).filter(Boolean));
    nextToken = connection?.nextToken;
    if (!nextToken) break;
  }
  return rows;
}

async function moderate(variables: Record<string, string | undefined>): Promise<Receipt> {
  const client = generateClient({ authMode: "userPool" });
  const result = (await client.graphql({ query: MODERATE, variables })) as GraphResult;
  if (result.errors?.length) return { status: "refused", message: result.errors[0]?.message ?? "The action failed." };
  return (result.data?.moderateReader as Receipt | null) ?? { status: "refused", message: "The action did not answer." };
}

export type ModerationViewProps = {
  mode: unknown;
  queue: ModerationRow[];
  hidden: ModerationRow[];
  log: ActionEntry[];
  tab: "queue" | "hidden" | "log";
  busy: boolean;
  status: string;
  reason: string;
  onTab: (tab: "queue" | "hidden" | "log") => void;
  onReason: (reason: string) => void;
  onAction: (action: ModerationActionName, targetType: ModerationTarget, target: string, undoOf?: string) => void;
  onRefresh: () => void;
};

function Row({ row, busy, onAction, listed }: { row: ModerationRow; busy: boolean; onAction: ModerationViewProps["onAction"]; listed: "queue" | "hidden" }) {
  const kind = row.kind === "submission" ? "Submission" : "Comment";
  return (
    <li data-moderation-row={row.id}>
      <article aria-label={`${kind} by ${shortReader(row.readerId, row.handle)}`}>
        <p>
          <strong>{kind}</strong> by {shortReader(row.readerId, row.handle)} <time dateTime={row.createdAt}>{row.createdAt}</time> ({row.state}
          {row.reports.length > 0 ? `, ${row.reports.length} ${row.reports.length === 1 ? "report" : "reports"}` : ""})
        </p>
        {row.kind === "submission" ? (
          <p>
            {row.url ? (
              <a href={row.url} target="_blank" rel="noopener noreferrer nofollow">{row.title}</a>
            ) : (
              <span>{row.title}</span>
            )}
          </p>
        ) : null}
        {row.text ? <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{row.text}</p> : null}
        {row.signals.length > 0 ? (
          <ul aria-label="Automatic signals">
            {row.signals.map((signal, index) => (
              <li key={`${signal.detector}-${index}`}>Signal ({signal.severity}): {signal.policy} / {signal.detector}{signal.excerpt ? ` — “${signal.excerpt}”` : ""}</li>
            ))}
          </ul>
        ) : null}
        {row.reports.length > 0 ? (
          <ul aria-label="Reports">
            {row.reports.map((report) => (
              <li key={report.id}>Reported: {report.reason}</li>
            ))}
          </ul>
        ) : null}
        <p>
          {listed === "queue" ? (
            <button type="button" disabled={busy} onClick={() => onAction("approve", row.kind, row.id)}>Approve</button>
          ) : (
            <button type="button" disabled={busy} onClick={() => onAction("unhide", row.kind, row.id)}>Show again</button>
          )}{" "}
          {row.state !== "hidden" ? <button type="button" disabled={busy} onClick={() => onAction("hide", row.kind, row.id)}>Hide</button> : null}{" "}
          {row.canPromote ? <button type="button" disabled={busy} onClick={() => onAction("promote", row.kind, row.id)}>Promote to a draft</button> : null}{" "}
          <button type="button" disabled={busy} onClick={() => onAction("ban", "reader", row.readerId)}>Ban reader</button>{" "}
          <button type="button" disabled={busy} onClick={() => onAction("limit", "reader", row.readerId)}>Limit reader</button>
        </p>
      </article>
    </li>
  );
}

export function ModerationView(props: ModerationViewProps) {
  const { queue, hidden, log, tab, busy } = props;
  return (
    <section aria-labelledby="newsroom-moderation-title" data-news-desk-admin-panel="moderation">
      <h3 id="newsroom-moderation-title">Moderation</h3>
      <p>{moderationModeText(props.mode)} Only editors and admins can see this.</p>
      <p role="tablist" aria-label="Moderation views">
        <button type="button" role="tab" aria-selected={tab === "queue"} onClick={() => props.onTab("queue")}>Queue ({queue.length})</button>{" "}
        <button type="button" role="tab" aria-selected={tab === "hidden"} onClick={() => props.onTab("hidden")}>Hidden ({hidden.length})</button>{" "}
        <button type="button" role="tab" aria-selected={tab === "log"} onClick={() => props.onTab("log")}>Recent actions</button>{" "}
        <button type="button" onClick={props.onRefresh} disabled={busy}>Refresh</button>
      </p>
      <label>
        Reason for the next action (optional){" "}
        <input type="text" value={props.reason} maxLength={500} onChange={(event) => props.onReason(event.target.value)} />
      </label>
      <p role="status" aria-live="polite">{props.status}</p>
      {tab === "queue" ? (
        queue.length === 0 ? <p>Nothing is waiting for a decision.</p> : <ul>{queue.map((row) => <Row key={row.id} row={row} busy={busy} onAction={props.onAction} listed="queue" />)}</ul>
      ) : null}
      {tab === "hidden" ? (
        hidden.length === 0 ? <p>Nothing is hidden.</p> : <ul>{hidden.map((row) => <Row key={row.id} row={row} busy={busy} onAction={props.onAction} listed="hidden" />)}</ul>
      ) : null}
      {tab === "log" ? (
        log.length === 0 ? <p>No moderation actions yet.</p> : (
          <table>
            <thead>
              <tr><th scope="col">When</th><th scope="col">Action</th><th scope="col">Target</th><th scope="col">By</th><th scope="col">Reason</th><th scope="col"><span>Undo</span></th></tr>
            </thead>
            <tbody>
              {log.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.at}</td>
                  <td>{entry.label} ({entry.fromState} to {entry.toState}){entry.undoneBy ? ", undone" : ""}</td>
                  <td>{entry.targetType} {entry.target.slice(0, 12)}</td>
                  <td>{entry.byLabel}</td>
                  <td>{entry.reason}</td>
                  <td>
                    {entry.undoable ? (
                      <button type="button" disabled={busy} onClick={() => props.onAction("undo", entry.targetType as ModerationTarget, entry.target, entry.id)}>Undo</button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : null}
    </section>
  );
}

export function ModerationPanel() {
  const mode = useMemo(() => pluginSettings(amplifyOutputs as PluginOutputs, "reader-steering")?.moderation, []);
  const [tab, setTab] = useState<"queue" | "hidden" | "log">("queue");
  const [data, setData] = useState<{ queue: ModerationRow[]; hidden: ModerationRow[]; log: ActionEntry[] } | null>(null);
  const [status, setStatus] = useState("Loading...");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  const refresh = useCallback(async (quiet = false) => {
    setBusy(true);
    try {
      const [newSubmissions, newComments, hiddenSubmissions, hiddenComments, reports, actions, handleRows] = await Promise.all([
        loadAll<SubmissionRow>(QUEUE_SUBMISSIONS, "listReaderSubmissionsByModerationAndCreatedAt"),
        loadAll<CommentRow>(QUEUE_COMMENTS, "listReaderCommentsByModerationAndCreatedAt"),
        loadAll<SubmissionRow>(HIDDEN_SUBMISSIONS, "listReaderSubmissions"),
        loadAll<CommentRow>(HIDDEN_COMMENTS, "listReaderComments"),
        loadAll<ReportRow>(OPEN_REPORTS, "listReaderReports"),
        loadAll<ActionRow>(ACTIONS, "listModerationActions"),
        loadAll<{ id: string; readerId: string }>(HANDLES, "listReaderHandles"),
      ]);
      const handles = Object.fromEntries(handleRows.map((row) => [row.readerId, row.id]));
      setData({
        queue: buildQueue({ submissions: newSubmissions, comments: newComments, reports, handles }),
        hidden: buildHidden({ submissions: hiddenSubmissions, comments: hiddenComments, reports, handles }),
        log: buildActionLog(actions),
      });
      if (!quiet) setStatus("");
    } catch (error) {
      setStatus(`Error: ${error instanceof Error ? error.message : "Could not load moderation data."}`);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onAction = useCallback(
    async (action: ModerationActionName, targetType: ModerationTarget, target: string, undoOf?: string) => {
      setBusy(true);
      setStatus("Working...");
      try {
        const receipt = await moderate({ action, targetType, target, ...(reason.trim() ? { reason: reason.trim() } : {}), ...(undoOf ? { undoOf } : {}) });
        setStatus(receiptMessage(receipt));
        if (receipt.status === "ok") setReason("");
      } catch (error) {
        setStatus(`Error: ${error instanceof Error ? error.message : "The action failed."}`);
      }
      await refresh(true);
    },
    [reason, refresh],
  );

  return (
    <ModerationView
      mode={mode}
      queue={data?.queue ?? []}
      hidden={data?.hidden ?? []}
      log={data?.log ?? []}
      tab={tab}
      busy={busy}
      status={status}
      reason={reason}
      onTab={setTab}
      onReason={setReason}
      onAction={(action, targetType, target, undoOf) => void onAction(action, targetType, target, undoOf)}
      onRefresh={() => void refresh()}
    />
  );
}
