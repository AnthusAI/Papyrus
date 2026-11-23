"use client";

import { useState } from "react";
import { pauseText, resumeText, wakeText, type PauseShown, type PauseResult, type ResumeResult, type WakeResult } from "../lib/agent-poke-in";

/** What the Automation page knows of the pauses: read, not readable by this person (pausing is for admins), or not read yet. */
export type PausesState = { state: "loaded"; site: PauseShown; agents: Record<string, PauseShown> } | { state: "forbidden"; message: string } | { state: "unavailable"; message: string } | null;

export type PokeInHandlers = {
  pauses: PausesState;
  onPause: (agent: string | null, reason: string) => Promise<PauseResult>;
  onResume: (agent: string | null, reason: string) => Promise<ResumeResult>;
  onWake: (agent: string, subject: string, reason: string) => Promise<WakeResult>;
};

type Phase = "idle" | "working" | "done";

/**
 * Pause or resume the whole site (`agent` null) or one agent, with a reason. The status is words with a mark. Pausing is a new version of the agent policy, so
 * nothing changes without a reason; the agent-policy function admits only an admin signed in here, and a refusal is shown in its own words.
 */
export function PauseControl({ agent, name, handlers, initialMessage = null }: { agent: string | null; name: string; handlers: PokeInHandlers; initialMessage?: string | null }) {
  const [reason, setReason] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(initialMessage);
  const pauses = handlers.pauses;
  const id = agent ?? "site";
  if (pauses === null) return <p className="news-desk-delegation-note" data-agent-pause={id} data-agent-pause-state="loading" role="status">Reading whether {name} is paused…</p>;
  if (pauses.state !== "loaded") {
    return <p className="news-desk-delegation-note" data-agent-pause={id} data-agent-pause-state={pauses.state}>{pauses.message}</p>;
  }
  const shown = agent === null ? pauses.site : pauses.agents[agent];
  const status = pauseText(shown, name);
  const paused = Boolean(shown?.paused);

  async function act() {
    if (!reason.trim()) {
      setMessage(`Say why ${paused ? "it resumes" : "it pauses"}: the reason is kept with the change.`);
      return;
    }
    setPhase("working");
    try {
      if (paused) setMessage(resumeText(await handlers.onResume(agent, reason), name));
      else {
        await handlers.onPause(agent, reason);
        setMessage(`${name} paused. Its next run starts nothing and says why.`);
      }
      setReason("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nothing was changed.");
    }
    setPhase("done");
  }

  return (
    <div data-agent-pause={id} data-agent-pause-state={paused ? "paused" : "running"} role="group" aria-label={`Pause or resume ${name}`}>
      <p data-agent-pause-status><span aria-hidden="true">{status.mark} </span>{status.words}</p>
      <label>
        Reason
        <input type="text" value={reason} onChange={(event) => setReason(event.target.value)} placeholder={paused ? "Why it resumes" : "Why it pauses"} data-agent-pause-reason />
      </label>
      <button type="button" onClick={() => void act()} disabled={phase === "working"} data-agent-pause-action={paused ? "resume" : "pause"}>
        {phase === "working" ? (paused ? "Resuming…" : "Pausing…") : paused ? `Resume ${name}` : `Pause ${name}`}
      </button>
      {message ? <p className="news-desk-delegation-note" role="status" data-agent-pause-message>{message}</p> : null}
    </div>
  );
}

/** Wake one agent now for one subject: its latest wake for that subject runs once more. Editors and admins. */
export function WakeNowControl({ agent, handlers, initialMessage = null }: { agent: string; handlers: PokeInHandlers; initialMessage?: string | null }) {
  const [subject, setSubject] = useState("");
  const [reason, setReason] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(initialMessage);

  async function wake() {
    if (!subject.trim() || !reason.trim()) {
      setMessage("Name the subject (a Story's lineage id, or the record its wakes name) and say why.");
      return;
    }
    setPhase("working");
    try {
      setMessage(wakeText(await handlers.onWake(agent, subject, reason)));
      setSubject("");
      setReason("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nothing was sent.");
    }
    setPhase("done");
  }

  return (
    <div data-agent-wake={agent} role="group" aria-label={`Wake ${agent} now`}>
      <label>
        Subject
        <input type="text" value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="A Story's lineage id" data-agent-wake-subject />
      </label>
      <label>
        Reason
        <input type="text" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why now" data-agent-wake-reason />
      </label>
      <button type="button" onClick={() => void wake()} disabled={phase === "working"} data-agent-wake-start>
        {phase === "working" ? "Waking…" : "Wake now"}
      </button>
      {message ? <p className="news-desk-delegation-note" role="status" data-agent-wake-message>{message}</p> : null}
    </div>
  );
}
