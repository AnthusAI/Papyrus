"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { LOCAL_PREVIEW_TENANTS, getLocalPreviewTenantId, setLocalPreviewTenantId } from "../lib/local-preview-tenant";
import { createProspectusAccount, loadProspectusAccountState, selectProspectusAccount, type ProspectusAccountState } from "../lib/prospectus-account-client";

/** Local preview: add ?no-accounts=1 to the address to see a signed-in person with no publishing account. */
function previewHasNoAccounts(): boolean {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).has("no-accounts");
}

function previewAccountState(): ProspectusAccountState {
  if (previewHasNoAccounts()) return { status: "signedIn", publishingAccounts: [], selectedAccountId: null, cyclotronLabAccess: false };
  return {
    status: "signedIn",
    publishingAccounts: LOCAL_PREVIEW_TENANTS.map(tenant => ({ accountId: tenant.accountId, name: tenant.name, role: tenant.role })),
    selectedAccountId: getLocalPreviewTenantId(),
    cyclotronLabAccess: true,
  };
}

const ACCOUNT_STATE_EVENT = "papyrus:prospectus-account-state";

function summaryOf(state: ProspectusAccountState): string | null {
  if (state.status !== "signedIn") return null;
  const selected = state.publishingAccounts.find(account => account.accountId === state.selectedAccountId);
  return selected ? `${selected.name ?? selected.accountId} · ${roleLabel(selected.role)}` : "Choose an account";
}

const roleLabel = (role: string) => role.replace(/_/g, " ");

/** The signed-in person's current publishing account as "Name · role", or null when the site has no Prospectus accounts. */
export function useProspectusAccountSummary(): string | null {
  const [summary, setSummary] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const returnPath = `${window.location.pathname}${window.location.search}`;
    (isLocalPreviewEnabled() ? Promise.resolve(previewAccountState()) : loadProspectusAccountState(returnPath)).then(loaded => {
      if (!cancelled) setSummary(summaryOf(loaded));
    });
    const onChange = (event: Event) => setSummary(summaryOf((event as CustomEvent<ProspectusAccountState>).detail));
    window.addEventListener(ACCOUNT_STATE_EVENT, onChange);
    return () => { cancelled = true; window.removeEventListener(ACCOUNT_STATE_EVENT, onChange); };
  }, []);
  return summary;
}

/**
 * The publishing account the signed-in person is acting as. It appears only on sites that have Prospectus
 * accounts configured; a site with its own user pool never shows it. Choosing an account records the choice
 * in the sign-in session and reloads so every page reads the new account.
 */
export function ProspectusAccountChooser() {
  const [state, setState] = useState<ProspectusAccountState>({ status: "unavailable" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  useEffect(() => {
    let cancelled = false;
    const returnPath = `${window.location.pathname}${window.location.search}`;
    (isLocalPreviewEnabled() ? Promise.resolve(previewAccountState()) : loadProspectusAccountState(returnPath))
      .then(loaded => { if (!cancelled) setState(loaded); });
    return () => { cancelled = true; };
  }, []);
  if (state.status === "unavailable") return null;
  if (state.status === "signedOut") {
    return <div className="organizer-account-chooser" data-prospectus-account-chooser="signed-out">
      <a className="organizer-account-chooser-link" href={state.signInUrl}>Sign in with Prospectus</a>
    </div>;
  }
  const choose = async (accountId: string) => {
    if (accountId === state.selectedAccountId || pending) return;
    setPending(accountId); setError(null);
    if (isLocalPreviewEnabled()) {
      setLocalPreviewTenantId(accountId);
      window.location.reload();
      return;
    }
    const result = await selectProspectusAccount(accountId);
    setPending(null);
    if ("error" in result) { setError(result.error); return; }
    window.location.reload();
  };
  const create = async () => {
    if (pending) return;
    setPending("create"); setError(null);
    if (isLocalPreviewEnabled()) {
      const name = newName.trim() || "New publishing account";
      setState({ status: "signedIn", publishingAccounts: [{ accountId: "preview-created-account", name, role: "owner" }], selectedAccountId: "preview-created-account", cyclotronLabAccess: false });
      setPending(null); setCreating(false);
      return;
    }
    const result = await createProspectusAccount(newName);
    setPending(null);
    if ("error" in result) { setError(result.error); return; }
    window.location.reload();
  };
  return <div className="organizer-account-chooser" data-prospectus-account-chooser="signed-in">
    <p className="organizer-account-chooser-heading">Publishing account</p>
    {state.publishingAccounts.length === 0
      ? <p className="organizer-account-chooser-note">No publishing accounts yet.</p>
      : <ul role="listbox" aria-label="Publishing account">
        {state.publishingAccounts.map(account => {
          const selected = account.accountId === state.selectedAccountId;
          return <li key={account.accountId} role="presentation">
            <button aria-selected={selected} data-selected={selected || undefined} disabled={pending !== null} onClick={() => { void choose(account.accountId); }} role="option" type="button">
              <span><strong>{account.name ?? account.accountId}</strong><small>{roleLabel(account.role)}</small></span>
              {selected ? <Check size={14} aria-label="Selected" /> : null}
            </button>
          </li>;
        })}
      </ul>}
    {state.publishingAccounts.length === 0 ? (
      creating
        ? <form className="organizer-account-create" data-prospectus-create-account onSubmit={event => { event.preventDefault(); void create(); }}>
          <label>Account name<input autoFocus disabled={pending !== null} maxLength={80} onChange={event => setNewName(event.target.value)} placeholder="Optional" type="text" value={newName} /></label>
          <span>
            <button data-prospectus-create-account-submit disabled={pending !== null} type="submit">{pending === "create" ? "Creating…" : "Create account"}</button>
            <button disabled={pending !== null} onClick={() => setCreating(false)} type="button">Cancel</button>
          </span>
        </form>
        : <button className="organizer-account-create-start" data-prospectus-create-account-start onClick={() => setCreating(true)} type="button">Create publishing account</button>
    ) : null}
    {!state.selectedAccountId && state.publishingAccounts.length > 0 ? <p className="organizer-account-chooser-note">Choose the account you are working as.</p> : null}
    {state.cyclotronLabAccess ? <p className="organizer-account-chooser-note" data-cyclotron-lab-access>Cyclotron lab access is on for you.</p> : null}
    {error ? <p className="organizer-account-chooser-note" role="alert">{error}</p> : null}
  </div>;
}
