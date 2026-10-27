"use client";

import { generateClient } from "aws-amplify/data";
import amplifyOutputs from "papyrus-amplify-outputs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ProposalsView } from "./proposals-view";
import { pluginSettings, type PluginOutputs } from "../lib/plugin-settings";
import {
  EDIT_PROPOSAL,
  LIST_PROPOSALS,
  TRANSITION_PROPOSAL,
  proposalReceiptMessage,
  type ProposalFilter,
  type ProposalMove,
  type ProposalReceipt,
  type ProposalRow,
} from "../lib/proposals-admin";

type GraphResult = { data?: Record<string, { items?: ProposalRow[]; nextToken?: string | null } | ProposalReceipt | null>; errors?: { message?: string }[] };
const MAXIMUM_PAGES = 20;

async function loadProposals(): Promise<ProposalRow[]> {
  const client = generateClient({ authMode: "userPool" });
  const rows: ProposalRow[] = [];
  let nextToken: string | null | undefined;
  for (let page = 0; page < MAXIMUM_PAGES; page += 1) {
    const result = (await client.graphql({ query: LIST_PROPOSALS, variables: { nextToken } })) as GraphResult;
    if (result.errors?.length) throw new Error(result.errors[0]?.message ?? "Could not load proposals.");
    const connection = result.data?.listProposals as { items?: ProposalRow[]; nextToken?: string | null } | undefined;
    rows.push(...(connection?.items ?? []).filter(Boolean));
    nextToken = connection?.nextToken;
    if (!nextToken) break;
  }
  return rows;
}

async function run(query: string, field: string, variables: Record<string, string | undefined>): Promise<ProposalReceipt> {
  const client = generateClient({ authMode: "userPool" });
  const result = (await client.graphql({ query, variables })) as GraphResult;
  if (result.errors?.length) return { status: "refused", message: result.errors[0]?.message ?? "The action failed." };
  return (result.data?.[field] as ProposalReceipt | null) ?? { status: "refused", message: "The action did not answer." };
}

/** One button: a path of states is one `transitionProposal` call per state, stopping at the first refusal; pin and hold are `editProposal`. */
async function perform(proposalId: string, move: ProposalMove, reason: string): Promise<ProposalReceipt> {
  if (move.edit) return run(EDIT_PROPOSAL, "editProposal", { proposalId, action: move.edit });
  let receipt: ProposalReceipt = { status: "refused", message: "Nothing to do." };
  for (const state of move.path ?? []) {
    receipt = await run(TRANSITION_PROPOSAL, "transitionProposal", { proposalId, state, ...(reason ? { reason } : {}) });
    if (receipt.status !== "ok") break;
  }
  return receipt;
}

/** Core to every site: it does not depend on the reader-steering plugin. */
export function ProposalsPanel() {
  const [rows, setRows] = useState<ProposalRow[]>([]);
  const [filter, setFilter] = useState<ProposalFilter>("open");
  const [status, setStatus] = useState("Loading...");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const readers = useMemo(() => pluginSettings(amplifyOutputs as PluginOutputs, "reader-steering") !== null, []);

  const refresh = useCallback(async (quiet = false) => {
    setBusy(true);
    try {
      setRows(await loadProposals());
      if (!quiet) setStatus("");
    } catch (error) {
      setStatus(`Error: ${error instanceof Error ? error.message : "Could not load proposals."}`);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onMove = useCallback(
    async (proposalId: string, move: ProposalMove) => {
      setBusy(true);
      setStatus("Working...");
      try {
        const receipt = await perform(proposalId, move, reason.trim());
        setStatus(proposalReceiptMessage(receipt));
        if (receipt.status === "ok") setReason("");
      } catch (error) {
        setStatus(`Error: ${error instanceof Error ? error.message : "The action failed."}`);
      }
      await refresh(true);
    },
    [reason, refresh],
  );

  return (
    <ProposalsView
      rows={rows}
      readers={readers}
      filter={filter}
      busy={busy}
      status={status}
      reason={reason}
      onFilter={setFilter}
      onReason={setReason}
      onMove={(proposalId, move) => void onMove(proposalId, move)}
      onRefresh={() => void refresh()}
    />
  );
}
