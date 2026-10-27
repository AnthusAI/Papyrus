"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  decideMonitoringEmailSubmission,
  importMonitoringEmailCandidates,
  loadMonitoringEmailSubmission,
  loadMonitoringOverview,
  resolveMonitoringEmailArticleLink,
} from "../lib/monitoring-client";
import { FIXTURE_ALL_PIPELINE_OVERVIEW, FIXTURE_MONITORING_OVERVIEW } from "../lib/monitoring-overview-fixture";
import type { EmailReferenceImportItem, MonitoringEmailDetails, MonitoringResult } from "../lib/monitoring-overview";
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

  const resolveEmailArticleLink = (receiptId: string, candidateIndex: number) =>
    resolveMonitoringEmailArticleLink(receiptId, candidateIndex);

  const importEmailCandidates = (receiptId: string, candidates: EmailReferenceImportItem[]) =>
    importMonitoringEmailCandidates(receiptId, candidates);

  return <MonitoringOverviewView result={result} canViewAll={isAdmin} mode={mode} onModeChange={setMode} demo={isDemo}
    emailDetail={emailDetail} onEmailOpen={isDemo ? () => {} : openEmail} onResolveArticleLink={isDemo ? undefined : resolveEmailArticleLink}
    onImportCandidates={importEmailCandidates} onDecide={isDemo ? undefined : decideMonitoringEmailSubmission} />;
}
