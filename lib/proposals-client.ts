"use client";

import { generateClient } from "aws-amplify/data";
import { EDIT_PROPOSAL, TRANSITION_PROPOSAL, type ProposalMove, type ProposalReceipt } from "./proposals-admin";

type GraphResult = { data?: Record<string, ProposalReceipt | null>; errors?: { message?: string }[] };

async function run(query: string, field: string, variables: Record<string, string | undefined>): Promise<ProposalReceipt> {
  const client = generateClient({ authMode: "userPool" });
  const result = (await client.graphql({ query, variables })) as GraphResult;
  if (result.errors?.length) return { status: "refused", message: result.errors[0]?.message ?? "The action failed." };
  return result.data?.[field] ?? { status: "refused", message: "The action did not answer." };
}

/** Moves a proposal through `path`, one `transitionProposal` call per state, stopping at the first refusal. */
export async function transitionProposalPath(proposalId: string, path: readonly string[], reason = ""): Promise<ProposalReceipt> {
  let receipt: ProposalReceipt = { status: "refused", message: "Nothing to do." };
  for (const state of path) {
    receipt = await run(TRANSITION_PROPOSAL, "transitionProposal", { proposalId, state, ...(reason ? { reason } : {}) });
    if (receipt.status !== "ok") break;
  }
  return receipt;
}

/** One button of the Proposals panel: a path of states, or `editProposal` for pin and hold. */
export async function performProposalMove(proposalId: string, move: ProposalMove, reason: string): Promise<ProposalReceipt> {
  if (move.edit) return run(EDIT_PROPOSAL, "editProposal", { proposalId, action: move.edit });
  return transitionProposalPath(proposalId, move.path ?? [], reason);
}
