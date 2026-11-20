"use client";

import { useEffect, useState } from "react";
import { FIXTURE_TODAY } from "../lib/today-fixture";
import { REFRESH_MILLISECONDS, type TodayResult } from "../lib/today-overview";
import { TodayView } from "./today-view";

/** Today on the newsroom home. It reads when it opens, when the tab comes back into focus, and every five minutes. No subscription. */
export function TodayPanel({ isDemo }: { isDemo: boolean }) {
  const [result, setResult] = useState<TodayResult | null>(null);

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

  return <TodayView demo={isDemo} result={result} />;
}
