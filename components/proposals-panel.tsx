"use client";

import { generateClient } from "aws-amplify/data";
import amplifyOutputs from "papyrus-amplify-outputs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ProposalsView } from "./proposals-view";
import { pluginSettings, type PluginOutputs } from "../lib/plugin-settings";
import {
  LIST_PROPOSALS,
  filterProposals,
  proposalReceiptMessage,
  withoutStoryDrafts,
  type ProposalFilter,
  type ProposalMove,
  type ProposalRow,
} from "../lib/proposals-admin";
import { performProposalMove } from "../lib/proposals-client";

type GraphResult = { data?: Record<string, { items?: ProposalRow[]; nextToken?: string | null } | null>; errors?: { message?: string }[] };
const MAXIMUM_PAGES = 20;

export async function loadProposals(): Promise<ProposalRow[]> {
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
  return withoutStoryDrafts(rows);
}

/** Core to every site: it does not depend on the reader-steering plugin. */
export function ProposalsPanel() {
  const [rows, setRows] = useState<ProposalRow[]>([]);
  const [filter, setFilter] = useState<ProposalFilter>("open");
  const [status, setStatus] = useState("Loading...");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [focusId, setFocusId] = useState<string | null>(null);
  const focused = useRef(false);
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

  // Sent here by a link such as `?proposal=<id>`: show the view that holds it and scroll to it.
  useEffect(() => {
    setFocusId(new URLSearchParams(window.location.search).get("proposal"));
  }, []);
  useEffect(() => {
    if (!focusId || focused.current) return;
    const row = rows.find((candidate) => candidate.id === focusId);
    if (!row) return;
    focused.current = true;
    setFilter(filterProposals([row], "open").length ? "open" : "decided");
    window.requestAnimationFrame(() => document.getElementById(`proposal-${focusId}`)?.scrollIntoView({ block: "start" }));
  }, [focusId, rows]);

  const onMove = useCallback(
    async (proposalId: string, move: ProposalMove) => {
      setBusy(true);
      setStatus("Working...");
      try {
        const receipt = await performProposalMove(proposalId, move, reason.trim());
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
      focusId={focusId}
    />
  );
}
