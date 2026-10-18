"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { loadProspectusAccountState, selectProspectusAccount, type ProspectusAccountState } from "../lib/prospectus-account-client";

const PREVIEW_ACCOUNT_STATE: ProspectusAccountState = {
  status: "signedIn",
  publishingAccounts: [
    { accountId: "preview-papyrus", name: "Papyrus", role: "publisher" },
    { accountId: "preview-pilobolus", name: "Pilobolus", role: "editor" },
  ],
  selectedAccountId: "preview-papyrus",
  cyclotronLabAccess: true,
};

const roleLabel = (role: string) => role.replace(/_/g, " ");

/**
 * The publishing account the signed-in person is acting as. It appears only on sites that have Prospectus
 * accounts configured; a site with its own user pool never shows it. Choosing an account records the choice
 * in the sign-in session and reloads so every page reads the new account.
 */
export function ProspectusAccountChooser() {
  const [state, setState] = useState<ProspectusAccountState>({ status: "unavailable" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const returnPath = `${window.location.pathname}${window.location.search}`;
    (isLocalPreviewEnabled() ? Promise.resolve(PREVIEW_ACCOUNT_STATE) : loadProspectusAccountState(returnPath))
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
      setState({ ...state, selectedAccountId: accountId }); setPending(null); return;
    }
    const result = await selectProspectusAccount(accountId);
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
    {!state.selectedAccountId && state.publishingAccounts.length > 0 ? <p className="organizer-account-chooser-note">Choose the account you are working as.</p> : null}
    {state.cyclotronLabAccess ? <p className="organizer-account-chooser-note" data-cyclotron-lab-access>Cyclotron lab access is on for you.</p> : null}
    {error ? <p className="organizer-account-chooser-note" role="alert">{error}</p> : null}
  </div>;
}
