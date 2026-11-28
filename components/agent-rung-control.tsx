"use client";

import { Gauge } from "lucide-react";
import { useState } from "react";
import { rungChangeText, rungLabel, rungText, type RungAgent, type RungChange } from "../lib/agent-rungs";

/** What the Automation page knows of the rungs: read, not readable by this person (setting a rung is for admins), or not read yet. */
export type RungsState = { state: "loaded"; agents: RungAgent[] } | { state: "forbidden"; message: string } | { state: "unavailable"; message: string } | null;

export type RungHandlers = {
  rungs: RungsState;
  onSetRung: (agent: string, rung: string, reason: string) => Promise<RungChange>;
};

type Phase = "idle" | "working" | "done";

/**
 * How far one agent may go on this site, and changing it, with a reason. The choices are the rungs its definition uses (never above, never publish_auto); the
 * agent-policy function admits only an admin signed in here and saves a new version of the agent policy with who, when and why.
 */
export function RungControl({ responsibility, handlers, initialMessage = null }: { responsibility: string; handlers: RungHandlers; initialMessage?: string | null }) {
  const rungs = handlers.rungs;
  const shown = rungs?.state === "loaded" ? rungs.agents.find((item) => item.responsibility === responsibility) : undefined;
  const [choice, setChoice] = useState<string>(shown?.rung ?? "");
  const [reason, setReason] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(initialMessage);
  if (rungs === null) return <p className="news-desk-delegation-note" data-agent-rung={responsibility} data-agent-rung-state="loading" role="status">{`Reading ${responsibility}'s setting…`}</p>;
  if (rungs.state !== "loaded") return <p className="news-desk-delegation-note" data-agent-rung={responsibility} data-agent-rung-state={rungs.state}>{rungs.message}</p>;
  if (!shown) {
    return <p className="news-desk-delegation-note" data-agent-rung={responsibility} data-agent-rung-state="unknown">{`${responsibility} is not one of this site's registered agents, so there is nothing to set here.`}</p>;
  }
  const selected = choice || shown.rung;

  async function save() {
    if (!shown) return;
    if (selected === shown.rung) {
      setMessage(`${responsibility} is already set to ${rungLabel(shown.rung)}. Choose another setting to change it.`);
      return;
    }
    if (!reason.trim()) {
      setMessage("Say why: the reason is kept with the change.");
      return;
    }
    setPhase("working");
    try {
      setMessage(rungChangeText(await handlers.onSetRung(shown.id, selected, reason)));
      setReason("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nothing was changed.");
    }
    setPhase("done");
  }

  return (
    <div data-agent-rung={responsibility} data-agent-rung-state="loaded" data-agent-rung-current={shown.rung} role="group" aria-label={`Set how far ${responsibility} may go`}>
      <p data-agent-rung-status className="inline-flex items-center gap-1.5">
        <Gauge aria-hidden="true" size={16} />
        {`${responsibility}: ${rungText(shown.rung)}. The most it can be set to is ${rungLabel(shown.ceiling)}.`}
      </p>
      {shown.overrides ? <p className="news-desk-delegation-note" data-agent-rung-overrides>{`${shown.overrides} scoped ${shown.overrides === 1 ? "override keeps its" : "overrides keep their"} own rung; change those with papyrus agents set-rung --scope.`}</p> : null}
      <label>
        How far it may go
        <select value={selected} onChange={(event) => setChoice(event.target.value)} data-agent-rung-choice>
          {shown.choices.map((rung) => <option key={rung} value={rung}>{rungText(rung)}</option>)}
        </select>
      </label>
      <label>
        Reason
        <input type="text" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why it changes" data-agent-rung-reason />
      </label>
      <button type="button" onClick={() => void save()} disabled={phase === "working"} data-agent-rung-save>
        {phase === "working" ? "Saving…" : "Save"}
      </button>
      {message ? <p className="news-desk-delegation-note" role="status" data-agent-rung-message>{message}</p> : null}
    </div>
  );
}
