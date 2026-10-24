"use client";

import { useEffect, useState } from "react";
import { loadMonitoringEmailSubmission, loadMonitoringOverview } from "../lib/monitoring-client";
import { FIXTURE_ALL_PIPELINE_OVERVIEW, FIXTURE_MONITORING_OVERVIEW } from "../lib/monitoring-overview-fixture";
import type { MonitoringEmailDetails, MonitoringResult } from "../lib/monitoring-overview";
import { MonitoringOverviewView, type MonitoringMode } from "./monitoring-overview-view";

const REFRESH_MILLISECONDS = 60_000;

/** Administration, Monitoring: loads the overview, refreshes it each minute, and lets an admin widen it to the whole pipeline. */
export function MonitoringPanel({ isAdmin, isDemo }: { isAdmin: boolean; isDemo: boolean }) {
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

  return <MonitoringOverviewView result={result} canViewAll={isAdmin} mode={mode} onModeChange={setMode} demo={isDemo}
    emailDetail={emailDetail} onEmailOpen={openEmail} />;
}
