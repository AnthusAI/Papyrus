"use client";

import { useEffect, useState } from "react";
import { loadAutomationOverview, runAutomationNow } from "../lib/automation-client";
import { FIXTURE_AUTOMATION_OVERVIEW } from "../lib/automation-fixture";
import type { AutomationResult } from "../lib/automation-overview";
import { AutomationView } from "./automation-view";

const REFRESH_MILLISECONDS = 60_000;

/** Administration, Automation: loads the records and their recent runs, and refreshes each minute. */
export function AutomationPanel({ isDemo }: { isDemo: boolean }) {
  const [result, setResult] = useState<AutomationResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (isDemo) {
      setResult(FIXTURE_AUTOMATION_OVERVIEW);
      return;
    }
    let live = true;
    const refresh = async () => {
      try {
        const next = await loadAutomationOverview();
        if (live) setResult(next);
      } catch {
        if (live) setResult({ state: "unavailable" });
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [isDemo]);

  const runNow = isDemo ? undefined : async (automationId: string, input: Record<string, unknown> | null) => {
    const outcome = await runAutomationNow(automationId, input);
    try {
      setResult(await loadAutomationOverview());   // show the new run without waiting for the minute
    } catch {
      /* the next refresh will */
    }
    return outcome;
  };

  return <AutomationView result={result} selectedId={selectedId} onSelect={setSelectedId} demo={isDemo} onRunNow={runNow} />;
}
