"use client";

import { useEffect, useRef, useState } from "react";
import { fetchAuthSession } from "aws-amplify/auth";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import {
  DEFAULT_DELEGATION_HOURS,
  MAXIMUM_DELEGATION_HOURS,
  MINIMUM_DELEGATION_HOURS,
  buildDelegatedCommandLine,
  delegationExpiryText,
  describeDelegationError,
  validateDelegationInput,
  type CurationDelegationRecord,
} from "../lib/curation-delegation-helpers";
import { createCurationDelegation, listCurationDelegations, revokeCurationDelegation, type CreatedCurationDelegation } from "./curation-delegation-client";

type IssuedToken = { agentLabel: string; token: string };

async function readSignedInEmail(): Promise<string> {
  if (isLocalPreviewEnabled()) return "ryan@example.com";
  try {
    const session = await fetchAuthSession();
    const email = session.tokens?.idToken?.payload?.email;
    return typeof email === "string" ? email : "";
  } catch {
    return "";
  }
}

export function AdministrationDelegationsPanel({ disabled }: { disabled: boolean }) {
  const [agentLabelText, setAgentLabelText] = useState("");
  const [hoursText, setHoursText] = useState(String(DEFAULT_DELEGATION_HOURS));
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  const [copied, setCopied] = useState<"token" | "command" | null>(null);
  const [email, setEmail] = useState("");
  const [delegations, setDelegations] = useState<CurationDelegationRecord[]>([]);
  const [confirmingRevokeId, setConfirmingRevokeId] = useState<string | null>(null);
  const [nowMilliseconds, setNowMilliseconds] = useState(() => Date.now());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void readSignedInEmail().then((value) => {
      if (mounted.current) setEmail(value);
    });
    void refreshDelegations();
    const timer = window.setInterval(() => setNowMilliseconds(Date.now()), 30_000);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      setIssued(null);
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

  async function handleCreate() {
    const validation = validateDelegationInput(agentLabelText, hoursText);
    if (!validation.ok) {
      setErrorMessage(validation.message);
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    try {
      const created: CreatedCurationDelegation = await createCurationDelegation(validation.agentLabel, validation.hours);
      setIssued({ agentLabel: created.agentLabel, token: created.token });
      setCopied(null);
      await refreshDelegations();
      setAgentLabelText("");
      setNowMilliseconds(Date.now());
    } catch (error) {
      setErrorMessage(describeDelegationError(error));
    } finally {
      setBusy(false);
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

  async function copyText(kind: "token" | "command", text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
    } catch {
      setErrorMessage("Copying was blocked by the browser. Select the text and copy it by hand.");
    }
  }

  const commandLine = issued ? buildDelegatedCommandLine({ email, agentLabel: issued.agentLabel, token: issued.token }) : "";

  return (
    <div data-news-desk-admin-panel="delegations">
      <article className="news-desk-doctrine-card">
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Agent delegations</h3>
            <span>Let one agent approve or reject References for you, for a short time</span>
          </div>
        </div>
        <p className="news-desk-delegation-note">
          A delegation is a token you hand to one named agent. While it lasts, that agent&apos;s approvals and rejections are recorded under your name and marked as relayed. You can revoke it at any moment.
        </p>
        <p className="news-desk-delegation-note" data-delegation-words-note>
          The agent must pass your actual words, in quotes, as the instruction on every approval or rejection. Papyrus keeps those words with the record. An agent that paraphrases or invents them is not following this delegation.
        </p>
        <div className="news-desk-delegation-form">
          <label className="news-desk-doctrine-card__field">
            <span>Agent name</span>
            <input value={agentLabelText} onChange={(event) => setAgentLabelText(event.target.value)} placeholder="curator-agent" autoComplete="off" disabled={disabled || busy} />
          </label>
          <label className="news-desk-doctrine-card__field">
            <span>{`Hours (${MINIMUM_DELEGATION_HOURS} to ${MAXIMUM_DELEGATION_HOURS})`}</span>
            <input value={hoursText} onChange={(event) => setHoursText(event.target.value)} inputMode="numeric" disabled={disabled || busy} />
          </label>
          <button type="button" className="news-desk-primary-action-button" data-delegation-create onClick={() => void handleCreate()} disabled={disabled || busy}>
            {busy && !issued ? "Creating" : "Create delegation"}
          </button>
        </div>
        {errorMessage ? <p className="news-desk-delegation-error" role="alert" data-delegation-error>{errorMessage}</p> : null}
      </article>

      {issued ? (
        <article className="news-desk-delegation-token" data-delegation-token-box aria-live="polite">
          <h3>Copy this token now</h3>
          <p>This token is shown once. Papyrus does not keep it, and it cannot be shown again. If you lose it, revoke the delegation and create a new one.</p>
          <div className="news-desk-delegation-token__row">
            <code data-delegation-token>{issued.token}</code>
            <button type="button" onClick={() => void copyText("token", issued.token)}>{copied === "token" ? "Copied" : "Copy token"}</button>
          </div>
          <p className="story-label">Command line for {issued.agentLabel}</p>
          <div className="news-desk-delegation-token__row">
            <code data-delegation-command>{commandLine}</code>
            <button type="button" onClick={() => void copyText("command", commandLine)}>{copied === "command" ? "Copied" : "Copy command"}</button>
          </div>
          <div className="news-desk-doctrine-card__actions">
            <button type="button" className="news-desk-primary-action-button" data-delegation-done onClick={() => { setIssued(null); setCopied(null); }}>Done</button>
          </div>
        </article>
      ) : null}

      <article className="news-desk-doctrine-card">
        <div className="news-desk-doctrine-card__header">
          <div>
            <h3>Delegations</h3>
            <span>Granted by you, newest first</span>
          </div>
        </div>
        {delegations.length === 0 ? (
          <p className="news-desk-delegation-note" data-delegation-empty>You have not granted any delegations.</p>
        ) : (
          <ul className="news-desk-delegation-list">
            {delegations.map((entry) => {
              const stateText = delegationExpiryText(entry.expiresAt, entry.revokedAt, nowMilliseconds);
              const live = !entry.revokedAt && stateText !== "Expired";
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
