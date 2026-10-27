/**
 * The data side of the Administration "Proposals" panel, which every site has (the queue is core; the reader-steering
 * plugin only adds reader votes). Rows come from the staff-readable `Proposal` model; an editor moves one with the
 * `transitionProposal` mutation. Pure functions, no network, so the rules the panel shows can be tested.
 */

export type ProposalRow = {
  id: string;
  kind: string;
  title: string;
  summary?: string | null;
  body?: string | null;
  state: string;
  proposer?: string | null;
  held?: boolean | null;
  pinned?: boolean | null;
  createdAt: string;
};

export type ProposalFilter = "open" | "draft" | "in_steering" | "editor_review" | "decided";
/** A button: the states it moves through in order (one call each) or, for pin and hold, the `editProposal` action it runs. */
export type ProposalMove = { label: string; path?: string[]; edit?: "pin" | "unpin" | "hold" | "release"; state?: string };

const STATE_LABELS: Record<string, string> = {
  draft: "Draft",
  in_steering: "In steering",
  editor_review: "Editor review",
  approved: "Approved",
  declined: "Declined",
  overridden_by_editor: "Decided by an editor",
};

const KIND_LABELS: Record<string, string> = {
  story_draft: "Story draft",
  new_concept: "New concept",
  rename: "Rename",
  merge: "Merge",
  split: "Split",
  new_column: "New column",
  element_symbol: "Element symbol",
};

const DECIDED = new Set(["approved", "declined", "overridden_by_editor"]);

/**
 * What an editor may do next; the function enforces the same table (overriding the community needs a reason and is not offered
 * here). On a site without reader-steering nobody steers, so a draft goes straight to editor review (two moves) and the
 * "in steering" wording never shows.
 */
function stateMoves(state: string, readers: boolean): ProposalMove[] {
  if (state === "draft") {
    return readers
      ? [{ label: "Send to steering", path: ["in_steering"] }, { label: "Decline", path: ["declined"] }]
      : [{ label: "Move to editor review", path: ["in_steering", "editor_review"] }, { label: "Decline", path: ["declined"] }];
  }
  if (state === "in_steering") return [{ label: "Move to editor review", path: ["editor_review"] }];
  if (state === "editor_review") return [{ label: "Approve", path: ["approved"] }, { label: "Decline", path: ["declined"] }];
  return [];
}

export const PROPOSAL_FIELDS = "id kind title summary body state proposer held pinned createdAt";
export const LIST_PROPOSALS = `query Proposals($nextToken: String) { listProposals(limit: 500, nextToken: $nextToken) { items { ${PROPOSAL_FIELDS} } nextToken } }`;
export const EDIT_PROPOSAL = `mutation Edit($proposalId: String!, $action: String!) { editProposal(proposalId: $proposalId, action: $action) { status id error message } }`;
export const TRANSITION_PROPOSAL = `mutation Move($proposalId: String!, $state: String!, $reason: String) { transitionProposal(proposalId: $proposalId, state: $state, reason: $reason) { status id error message } }`;

export function stateLabel(state: string, readers = true): string {
  if (!readers && state === "in_steering") return "Waiting for review";
  return STATE_LABELS[state] ?? state;
}

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

/** AI-filed proposals say "AI"; a reader's proposal says "Reader" (their id is never shown). */
export function proposerLabel(proposer: string | null | undefined): string {
  return proposer === "ai" ? "AI" : proposer ? "Reader" : "Unknown";
}

export function proposalMoves(row: Pick<ProposalRow, "state" | "held" | "pinned">, readers = true): ProposalMove[] {
  const edits: ProposalMove[] = [
    { label: row.pinned ? "Unpin" : "Pin", edit: row.pinned ? "unpin" : "pin" },
    ...(DECIDED.has(row.state) && !row.held ? [] : [{ label: row.held ? "Release hold" : "Hold", edit: (row.held ? "release" : "hold") as "release" | "hold" }]),
  ];
  // A proposal on hold refuses every state change until it is released.
  return [...(row.held ? [] : stateMoves(row.state, readers)), ...edits];
}

export function sortProposals(rows: ProposalRow[]): ProposalRow[] {
  return [...rows].sort((left, right) => right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id));
}

export function filterProposals(rows: ProposalRow[], filter: ProposalFilter): ProposalRow[] {
  if (filter === "open") return rows.filter((row) => !DECIDED.has(row.state));
  if (filter === "decided") return rows.filter((row) => DECIDED.has(row.state));
  return rows.filter((row) => row.state === filter);
}

export function countProposals(rows: ProposalRow[]): Record<ProposalFilter, number> {
  return {
    open: filterProposals(rows, "open").length,
    draft: filterProposals(rows, "draft").length,
    in_steering: filterProposals(rows, "in_steering").length,
    editor_review: filterProposals(rows, "editor_review").length,
    decided: filterProposals(rows, "decided").length,
  };
}

export type ProposalReceipt = { status?: string | null; id?: string | null; error?: string | null; message?: string | null };

export function proposalReceiptMessage(receipt: ProposalReceipt | null | undefined): string {
  if (!receipt) return "The action did not answer.";
  if (receipt.status === "ok") return "Done.";
  return receipt.message || receipt.error || "The action was refused.";
}
