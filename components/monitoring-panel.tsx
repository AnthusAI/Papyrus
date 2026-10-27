"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  decideMonitoringEmailSubmission,
  importMonitoringEmailCandidates,
  loadMonitoringEmailSubmission,
  loadMonitoringOverview,
  loadMonitoringPage,
  resolveMonitoringEmailArticleLink,
} from "../lib/monitoring-client";
import { FIXTURE_ALL_PIPELINE_OVERVIEW, FIXTURE_MONITORING_OVERVIEW } from "../lib/monitoring-overview-fixture";
import { withLoadedPages } from "../lib/monitoring-paging";
import type {
  EmailReferenceImportItem,
  MonitoringEmailDetails,
  MonitoringListName,
  MonitoringResult,
} from "../lib/monitoring-overview";
import type { MonitoringLoadedPages } from "../lib/monitoring-paging";
import { EmailSubmissions, MonitoringOverviewView, type MonitoringMode } from "./monitoring-overview-view";

const REFRESH_MILLISECONDS = 60_000;

/** A receipt URL mounts only the single-submission reader, never the overview. */
export function MonitoringPanel(props: { isAdmin: boolean; isDemo: boolean }) {
  const searchParams = useSearchParams();
  if (searchParams.has("receipt")) {
    return <MonitoringEmailReceipt key={searchParams.get("receipt")} receiptId={searchParams.get("receipt") ?? ""} isDemo={props.isDemo} />;
  }
  return <MonitoringOverviewPanel {...props} />;
}

function MonitoringEmailReceipt({ receiptId, isDemo }: { receiptId: string; isDemo: boolean }) {
  const [detail, setDetail] = useState<MonitoringEmailDetails | null>(null);
  useEffect(() => {
    if (!receiptId || isDemo) return;
    let live = true;
    void loadMonitoringEmailSubmission(receiptId).then(
      (next) => { if (live) setDetail(next); },
      () => { if (live) setDetail({ state: "unavailable" }); },
    );
    return () => { live = false; };
  }, [receiptId, isDemo]);
  if (!receiptId) return <p role="alert">A receipt is required to open a submission.</p>;
  if (isDemo) return <p role="status">Single email submissions require an editor session.</p>;
  return <div data-news-desk-admin-panel="monitoring">
    {detail === null ? <p role="status">Loading email submission…</p> :
      <EmailSubmissions items={"submission" in detail ? [detail.submission] : []} detail={detail}
        onResolveArticleLink={resolveMonitoringEmailArticleLink} onImportCandidates={importMonitoringEmailCandidates}
        onDecide={decideMonitoringEmailSubmission} />}
  </div>;
}

/** Overview refreshes apply only when no receipt was requested. */
function MonitoringOverviewPanel({ isAdmin, isDemo }: { isAdmin: boolean; isDemo: boolean }) {
  const [mode, setMode] = useState<MonitoringMode>("publication");
  const [result, setResult] = useState<MonitoringResult | null>(null);
  const [emailDetail, setEmailDetail] = useState<MonitoringEmailDetails | null>(null);
  // Pages the editor loaded beyond the newest page of each list. The 60 second refresh re-reads only the newest
  // page, so what was loaded stays on screen.
  const [loaded, setLoaded] = useState<MonitoringLoadedPages>({});
  const [heldOnly, setHeldOnly] = useState(false);
  const [held, setHeld] = useState<MonitoringLoadedPages["emailSubmissions"] | null>(null);
  const [loadingList, setLoadingList] = useState<MonitoringListName | null>(null);

  useEffect(() => {
    setLoaded({});
    setHeldOnly(false);
    setHeld(null);
  }, [mode]);

  useEffect(() => {
    if (isDemo) {
      setResult(mode === "all" ? FIXTURE_ALL_PIPELINE_OVERVIEW : FIXTURE_MONITORING_OVERVIEW);
      return;
    }
    let live = true;
    const refresh = async () => {
      try {
        const next = await loadMonitoringOverview(mode);
        if (live) setResult(next);
      } catch {
        if (live) setResult({ state: "unavailable" });
      }
    };
    setResult(null);
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [mode, isDemo]);

  const openEmail = async (receiptId: string) => {
    setEmailDetail({ state: "unavailable" });
    const next = await loadMonitoringEmailSubmission(receiptId);
    setEmailDetail(next);
  };

  // Appends the next page of a list, or (held filter) the next page of held messages.
  const loadMore = async (list: MonitoringListName) => {
    if (isDemo || !result || !("scope" in result) || loadingList) return;
    const current = withLoadedPages(result as never, loaded, heldOnly ? held : null);
    const cursor = current.cursors?.[list];
    if (!cursor) return;
    setLoadingList(list);
    try {
      const page = await loadMonitoringPage(list, cursor, mode, heldOnly && list === "emailSubmissions");
      if (!("rows" in page)) return;
      if (heldOnly && list === "emailSubmissions") {
        setHeld((existing) => ({ rows: [...(existing?.rows ?? []), ...page.rows] as never, cursor: page.cursor }));
      } else {
        setLoaded((existing) => ({ ...existing, [list]: { rows: [...(existing[list]?.rows ?? []), ...page.rows], cursor: page.cursor } }) as MonitoringLoadedPages);
      }
    } finally {
      setLoadingList(null);
    }
  };

  // Held for review restarts the email list at its newest held message, however old.
  const changeHeldOnly = async (next: boolean) => {
    setHeldOnly(next);
    setHeld(null);
    if (!next || isDemo) return;
    setLoadingList("emailSubmissions");
    try {
      const page = await loadMonitoringPage("emailSubmissions", null, mode, true);
      if ("rows" in page) setHeld({ rows: page.rows as never, cursor: page.cursor });
      else setHeldOnly(false);
    } finally {
      setLoadingList(null);
    }
  };

  const shown = result && "scope" in result ? withLoadedPages(result as never, loaded, heldOnly ? held ?? { rows: [], cursor: null } : null) : result;

  const resolveEmailArticleLink = (receiptId: string, candidateIndex: number) =>
    resolveMonitoringEmailArticleLink(receiptId, candidateIndex);

  const importEmailCandidates = (receiptId: string, candidates: EmailReferenceImportItem[]) =>
    importMonitoringEmailCandidates(receiptId, candidates);

  return <MonitoringOverviewView result={shown} canViewAll={isAdmin} mode={mode} onModeChange={setMode} demo={isDemo}
    emailDetail={emailDetail} onEmailOpen={isDemo ? () => {} : openEmail} onResolveArticleLink={isDemo ? undefined : resolveEmailArticleLink}
    onImportCandidates={importEmailCandidates} onDecide={isDemo ? undefined : decideMonitoringEmailSubmission}
    paging={isDemo ? undefined : { onLoadMore: (list) => void loadMore(list), loadingList, heldOnly, onHeldOnlyChange: (next) => void changeHeldOnly(next) }} />;
}
