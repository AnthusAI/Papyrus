"use client";

import { useEffect, useRef, useState } from "react";
import {
  delegationStateText,
  describeDelegationError,
  isPendingDelegation,
  pendingCountdownText,
  requestedHoursText,
  type CurationDelegationRecord,
} from "../lib/curation-delegation-helpers";
import { approveCurationDelegation, denyCurationDelegation, listCurationDelegations, revokeCurationDelegation } from "./curation-delegation-client";

const REFRESH_MILLISECONDS = 10_000;

export function AdministrationDelegationsPanel({ disabled }: { disabled: boolean }) {
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [delegations, setDelegations] = useState<CurationDelegationRecord[]>([]);
  const [confirmingRevokeId, setConfirmingRevokeId] = useState<string | null>(null);
  const [nowMilliseconds, setNowMilliseconds] = useState(() => Date.now());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void refreshDelegations();
    const refreshTimer = window.setInterval(() => void refreshDelegations(), REFRESH_MILLISECONDS);
    const clockTimer = window.setInterval(() => setNowMilliseconds(Date.now()), 1_000);
    return () => {
      mounted.current = false;
      window.clearInterval(refreshTimer);
      window.clearInterval(clockTimer);
    };
  }, []);

  async function refreshDelegations() {
    try {
      const listed = await listCurationDelegations();
      if (mounted.current) setDelegations(listed);
    } catch (error) {
      if (mounted.current) setErrorMessage(describeDelegationError(error));
    }
  }

  async function decide(userCode: string, decision: "approve" | "deny") {
    setBusyCode(userCode);
    setErrorMessage(null);
    try {
      await (decision === "approve" ? approveCurationDelegation(userCode) : denyCurationDelegation(userCode));
      await refreshDelegations();
    } catch (error) {
      setErrorMessage(describeDelegationError(error));
      await refreshDelegations();
    } finally {
      setBusyCode(null);
    }
  }

  async function handleRevoke(delegationId: string) {
    setBusy(true);
    setErrorMessage(null);
    try {
      await revokeCurationDelegation(delegationId);
      await refreshDelegations();
      setConfirmingRevokeId(null);
    } catch (error) {
      setErrorMessage(describeDelegationError(error));
    } finally {
      setBusy(false);
    }
  }

  const pending = delegations.filter((entry) => isPendingDelegation(entry, nowMilliseconds));
  const others = delegations.filter((entry) => entry.state !== "pending");

  return (
    <div data-news-desk-admin-panel="delegations">
      <article className="news-desk-doctrine-card" data-delegation-pending-block>
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Pending requests</h3>
            <span>An agent asked to record your decisions. Check the code matches what it showed you.</span>
          </div>
        </div>
        {errorMessage ? <p className="news-desk-delegation-error" role="alert" data-delegation-error>{errorMessage}</p> : null}
        {pending.length === 0 ? (
          <p className="news-desk-delegation-note" data-delegation-pending-empty>No agent is waiting for approval. A request appears here as soon as an agent asks.</p>
        ) : (
          <ul className="news-desk-delegation-pending-list">
            {pending.map((entry) => {
              const userCode = entry.userCode ?? "";
              const working = busyCode === userCode;
              return (
                <li key={entry.delegationId} data-delegation-pending={entry.delegationId}>
                  <div>
                    <strong>{entry.agentLabel}</strong>
                    <span>{requestedHoursText(entry.requestedHours)}</span>
                    <span className="news-desk-delegation-countdown" data-delegation-countdown>{pendingCountdownText(entry.pendingExpiresAt ?? entry.expiresAt, nowMilliseconds)}</span>
                  </div>
                  <code className="news-desk-delegation-code" data-delegation-user-code aria-label={`Code ${userCode.split("").join(" ")}`}>{userCode}</code>
                  <span className="news-desk-delegation-decision">
                    <button type="button" data-delegation-approve onClick={() => void decide(userCode, "approve")} disabled={disabled || working || busyCode !== null}>Approve</button>
                    <button type="button" data-delegation-deny onClick={() => void decide(userCode, "deny")} disabled={disabled || working || busyCode !== null}>Deny</button>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <p className="news-desk-delegation-note" data-delegation-words-note>
          While a delegation lasts, that agent&apos;s approvals and rejections are recorded under your name and marked as relayed, with the words you gave it kept with each record. You can revoke it at any moment.
        </p>
      </article>

      <article className="news-desk-doctrine-card">
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Delegations</h3>
            <span>Decided requests, newest first</span>
          </div>
        </div>
        {others.length === 0 ? (
          <p className="news-desk-delegation-note" data-delegation-empty>You have not granted any delegations.</p>
        ) : (
          <ul className="news-desk-delegation-list">
            {others.map((entry) => {
              const stateText = delegationStateText(entry, nowMilliseconds);
              const live = entry.state === "approved" && !entry.revokedAt && stateText !== "Expired";
              return (
                <li key={entry.delegationId} data-delegation-row={entry.delegationId} data-delegation-live={live || undefined}>
                  <div>
                    <strong>{entry.agentLabel}</strong>
                    <span>{`Granted by ${entry.grantorLabel ?? "you"}`}</span>
                  </div>
                  <span className="news-desk-delegation-state">{stateText}</span>
                  {live ? (
                    confirmingRevokeId === entry.delegationId ? (
                      <span className="news-desk-delegation-confirm">
                        <span>{`Stop ${entry.agentLabel} from curating for you?`}</span>
                        <button type="button" data-delegation-revoke-confirm onClick={() => void handleRevoke(entry.delegationId)} disabled={busy}>Revoke now</button>
                        <button type="button" onClick={() => setConfirmingRevokeId(null)} disabled={busy}>Keep</button>
                      </span>
                    ) : (
                      <button type="button" data-delegation-revoke onClick={() => setConfirmingRevokeId(entry.delegationId)} disabled={disabled || busy}>Revoke</button>
                    )
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </article>
    </div>
  );
}
