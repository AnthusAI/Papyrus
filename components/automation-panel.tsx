"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { generateClient } from "aws-amplify/data";
import { agentPokeInApi, createDemoPokeInApi, type AgentPokeInApi } from "../lib/agent-poke-in";
import { loadAutomationOverview, runAutomationNow } from "../lib/automation-client";
import { FIXTURE_AUTOMATION_OVERVIEW } from "../lib/automation-fixture";
import type { AutomationResult } from "../lib/automation-overview";
import type { PausesState, PokeInHandlers } from "./agent-poke-in-control";
import { AutomationView } from "./automation-view";

const REFRESH_MILLISECONDS = 60_000;

/** Administration, Automation: loads the records and their recent runs, and refreshes each minute. Pause, resume and wake now go through the poke-in doors. */
export function AutomationPanel({ isDemo }: { isDemo: boolean }) {
  const [result, setResult] = useState<AutomationResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pauses, setPauses] = useState<PausesState>(null);
  const pokeInApi = useMemo<AgentPokeInApi>(() => {
    if (isDemo) return createDemoPokeInApi();
    const client = generateClient({ authMode: "userPool" });
    return agentPokeInApi((request) => client.graphql(request) as Promise<unknown>);
  }, [isDemo]);

  const readPauses = useCallback(async () => {
    try {
      const read = await pokeInApi.pauses();
      setPauses({ state: "loaded", site: read.site, agents: read.agents });
    } catch (error) {
      const message = error instanceof Error ? error.message : "The pauses could not be read.";
      setPauses({ state: /admins|signed in/i.test(message) ? "forbidden" : "unavailable", message });
    }
  }, [pokeInApi]);

  useEffect(() => {
    void readPauses();
  }, [readPauses]);

  useEffect(() => {
    // A line on Today opens the runs of one automation: `?automation=<id>`.
    const requested = new URLSearchParams(window.location.search).get("automation");
    if (requested) setSelectedId(requested);
  }, []);

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

  const pokeIn: PokeInHandlers = {
    pauses,
    onPause: async (agent, reason) => {
      const answer = await pokeInApi.pause(agent, reason);
      await readPauses();
      return answer;
    },
    onResume: async (agent, reason) => {
      const answer = await pokeInApi.resume(agent, reason);
      await readPauses();
      return answer;
    },
    onWake: (agent, subject, reason) => pokeInApi.wake(agent, subject, reason),
  };

  return <AutomationView result={result} selectedId={selectedId} onSelect={setSelectedId} demo={isDemo} onRunNow={runNow} pokeIn={pokeIn} />;
}
