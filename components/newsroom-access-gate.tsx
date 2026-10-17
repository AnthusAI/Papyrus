"use client";

import { newsroomHref } from "../lib/newsroom-base-path";
import Link from "next/link";
import { SITE_BRAND } from "../lib/site-brand";
import type { NewsDeskShellState } from "../lib/news-desk-session";
import { cn } from "../lib/utils";
import { NewsroomOpsShell } from "./newsroom-ops-shell";
import { ReaderAuthControl } from "./reader-auth-control";
import { buttonVariants } from "./ui/button";

export function NewsDeskAccessGate({ shell, showSectionTabs = false }: { shell: NewsDeskShellState | null; showSectionTabs?: boolean }) {
  const accessPhase = shell?.phase ?? "checkingAccess";

  return (
    <NewsroomOpsShell
      activeTab="overview"
      appTitle={SITE_BRAND.appTitle}
      backHref="/"
      backLabel={SITE_BRAND.backToHomeLabel}
      headerActions={(
        <Link className={cn(buttonVariants({ variant: "ghost", size: "sm" }))} href="/settings">Settings</Link>
      )}
      pageTitle="Newsroom"
      showNavigation={showSectionTabs}
    >
      <section aria-live="polite" data-news-desk-access={accessPhase} data-news-desk-access-phase={accessPhase}>
        <div className="space-y-3 rounded-xl border border-border bg-card p-6">
          <p className="m-0 text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Access</p>
          <h2 className="m-0 font-sans text-xl font-semibold tracking-tight">{formatAccessTitle(shell)}</h2>
          <p className="m-0 text-sm text-muted-foreground">{formatAccessDetail(shell)}</p>
          {shell?.error ? <p className="text-sm text-destructive">{shell.error}</p> : null}
          <p className="m-0 text-sm text-foreground">{formatAccessActionDetail(shell)}</p>
          {shell?.phase === "signedOut" || shell?.phase === "error" ? (
            <div className="news-desk-access-panel__auth">
              <ReaderAuthControl postAuthPath={newsroomHref()} showIdentity />
            </div>
          ) : null}
        </div>
      </section>
    </NewsroomOpsShell>
  );
}

function formatAccessTitle(state: NewsDeskShellState | null): string {
  if (!state || state.phase === "checkingAccess") return "Checking Desk Credentials";
  if (state.phase === "loadingDesk") return "Loading Newsroom Records";
  if (state.phase === "forbidden") return "Editor Role Required";
  if (state.phase === "error") return "Newsroom Unavailable";
  return "Editor Sign-In Required";
}

function formatAccessDetail(state: NewsDeskShellState | null): string {
  if (!state || state.phase === "checkingAccess") return `${SITE_BRAND.appTitle} is checking the current browser session before loading steering state.`;
  if (state.phase === "loadingDesk") return `${SITE_BRAND.appTitle} verified the browser session and is loading private Newsroom records.`;
  if (state.phase === "forbidden") return "This account is signed in, but the Cognito session does not include the editor or admin group.";
  if (state.phase === "error") return `${SITE_BRAND.appTitle} could not verify this editor session or load the private Newsroom data.`;
  return "Sign in with an editor or admin account to inspect category, category tree, ontology, and graph steering.";
}

function formatAccessActionDetail(state: NewsDeskShellState | null): string {
  if (!state || state.phase === "checkingAccess") return "This should only take a moment. If it hangs, reload the page.";
  if (state.phase === "loadingDesk") return "Private records are loading from GraphQL. Large reference queues may take several seconds.";
  if (state.phase === "forbidden") return "Ask an admin to add this account to the editor or admin group, then sign out and back in.";
  if (state.phase === "error") return "Reload the page or check the local development console for the GraphQL error.";
  return "Use the login button above to authenticate with an editor or admin account.";
}
