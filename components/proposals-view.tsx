import { useMemo } from "react";
import {
  countProposals,
  filterProposals,
  kindLabel,
  proposalMoves,
  proposerLabel,
  sortProposals,
  stateLabel,
  type ProposalFilter,
  type ProposalMove,
  type ProposalRow,
} from "../lib/proposals-admin";

const FILTERS: Array<{ key: ProposalFilter; label: string }> = [
  { key: "open", label: "Open" },
  { key: "draft", label: "Proposed" },
  { key: "in_steering", label: "In steering" },
  { key: "editor_review", label: "Editor review" },
  { key: "decided", label: "Decided" },
];

export type ProposalsViewProps = {
  rows: ProposalRow[];
  /** True when the site has the reader-steering plugin; without it nothing reader-facing is shown. */
  readers: boolean;
  filter: ProposalFilter;
  busy: boolean;
  status: string;
  reason: string;
  onFilter: (filter: ProposalFilter) => void;
  onReason: (reason: string) => void;
  onMove: (proposalId: string, move: ProposalMove) => void;
  onRefresh: () => void;
  /** A proposal the editor was sent to (from the Notification Center): its draft opens and it is marked. */
  focusId?: string | null;
};

export function ProposalsView(props: ProposalsViewProps) {
  const sorted = useMemo(() => sortProposals(props.rows), [props.rows]);
  const counts = useMemo(() => countProposals(sorted), [sorted]);
  const shown = filterProposals(sorted, props.filter);
  return (
    <section aria-labelledby="newsroom-proposals-title" data-news-desk-admin-panel="proposals">
      <h3 id="newsroom-proposals-title">Proposed Stories</h3>
      <p>Proposed Stories and other changes that AI proposes. Editors pin, hold and decide them. Only editors and admins can see this.</p>
      <p role="tablist" aria-label="Proposal views">
        {FILTERS.filter((entry) => props.readers || entry.key !== "in_steering").map((entry) => (
          <span key={entry.key}>
            <button type="button" role="tab" aria-selected={props.filter === entry.key} onClick={() => props.onFilter(entry.key)}>
              {entry.label} ({counts[entry.key]})
            </button>{" "}
          </span>
        ))}
        <button type="button" onClick={props.onRefresh} disabled={props.busy}>Refresh</button>
      </p>
      <label>
        Reason for the next move (optional){" "}
        <input type="text" value={props.reason} maxLength={500} onChange={(event) => props.onReason(event.target.value)} />
      </label>
      <p role="status" aria-live="polite">{props.status}</p>
      {shown.length === 0 ? (
        <p>Nothing here.</p>
      ) : (
        <ul>
          {shown.map((row) => (
            <li key={row.id} id={`proposal-${row.id}`} data-proposal-row={row.id} data-proposal-focused={props.focusId === row.id || undefined}>
              <article aria-label={row.title}>
                <p>
                  <strong>{kindLabel(row.kind)}</strong>: {row.title} ({stateLabel(row.state, props.readers)}
                  {row.held ? ", on hold" : ""}) from {proposerLabel(row.proposer)} <time dateTime={row.createdAt}>{row.createdAt}</time>
                </p>
                {row.summary ? <p>{row.summary}</p> : null}
                {row.body ? (
                  <details open={props.focusId === row.id || undefined}>
                    <summary>Read the Proposed Story</summary>
                    <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{row.body}</pre>
                  </details>
                ) : null}
                <p>
                  {proposalMoves(row, props.readers).map((move) => (
                    <span key={move.label}>
                      <button type="button" disabled={props.busy} onClick={() => props.onMove(row.id, move)}>{move.label}</button>{" "}
                    </span>
                  ))}
                </p>
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

