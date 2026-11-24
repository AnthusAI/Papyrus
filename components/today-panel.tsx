"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FIXTURE_TODAY } from "../lib/today-fixture";
import { REFRESH_MILLISECONDS, withoutAttentionRun, type AcknowledgeResult, type OverdueWakeOutcome, type TodayResult } from "../lib/today-overview";
import { TodayView } from "./today-view";

/** Why acknowledging did not happen, in words for the editor; null when the run is off the list. */
function acknowledgeProblem(answer: AcknowledgeResult): string | null {
  if ("error" in answer) return answer.error === "forbidden" ? "Only editors and admins can do this." : answer.message ?? "The request was not understood.";
  if (answer.state === "refused") return answer.reason;
  if (answer.state === "unavailable") return "It could not be saved right now. Try again.";
  return null;
}

/** Today on the newsroom home. It reads when it opens, when the tab comes back into focus, and every five minutes. No subscription. */
export function TodayPanel({ isDemo }: { isDemo: boolean }) {
  const [result, setResult] = useState<TodayResult | null>(null);
  const refreshRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    if (isDemo) {
      setResult(FIXTURE_TODAY);
      return;
    }
    let live = true;
    const refresh = async () => {
      try {
        const { loadTodayOverview } = await import("../lib/today-client");
        const next = await loadTodayOverview();
        if (live) setResult(next);
      } catch {
        if (live) setResult((current) => current ?? { state: "unavailable" });   // a failed refresh keeps what is shown
      }
    };
    refreshRef.current = refresh;
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      live = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [isDemo]);

  /** Acknowledge a failure or settle an Outcome unknown. The demo takes it off the list in memory; nothing leaves the page. */
  const acknowledge = useCallback(async (runId: string): Promise<string | null> => {
    const takeOff = () => setResult((current) => (current && "state" in current && current.state === "ready" ? withoutAttentionRun(current, runId) : current));
    if (isDemo) {
      takeOff();
      return null;
    }
    const { acknowledgeTodayRun } = await import("../lib/today-client");
    const problem = acknowledgeProblem(await acknowledgeTodayRun(runId));
    if (problem) return problem;
    takeOff();
    void refreshRef.current();
    return null;
  }, [isDemo]);

  /** Wake now on an Overdue record. The demo sends nothing and says so. */
  const wakeOverdue = useCallback(async (record: string, id: string, reason: string): Promise<OverdueWakeOutcome> => {
    if (isDemo) return { state: "sent", words: `Demo: nothing was sent. On a site, the wake ${record} ${id}'s timer sends goes on the queue again, with the same key.` };
    const { wakeOverdueRecord } = await import("../lib/today-client");
    const outcome = await wakeOverdueRecord(record, id, reason);
    if (outcome.state === "sent") void refreshRef.current();
    return outcome;
  }, [isDemo]);

  return <TodayView demo={isDemo} onAcknowledge={acknowledge} onWakeOverdue={wakeOverdue} result={result} />;
}
