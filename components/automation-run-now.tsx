"use client";

import { useState } from "react";
import {
  inputTemplateText,
  parseRunInput,
  runNowMessage,
  type AutomationRecord,
  type RunNowResult,
} from "../lib/automation-overview";

export type RunNowPhase = "idle" | "confirming" | "running" | "done";

/**
 * "Run now": a button, then a confirm step that says what will start and, when the record's input names
 * placeholders for an item, asks for the input of this run. Starting costs money (the procedure calls a model),
 * so nothing starts on the first click. `initialPhase` and `initialMessage` exist so every step renders from a test.
 */
export function RunNowControl({
  record,
  demo = false,
  onRun,
  initialPhase = "idle",
  initialMessage = null,
}: {
  record: Pick<AutomationRecord, "id" | "title" | "procedureKey" | "runNow" | "limits">;
  demo?: boolean;
  onRun?: (automationId: string, input: Record<string, unknown> | null) => Promise<RunNowResult>;
  initialPhase?: RunNowPhase;
  initialMessage?: string | null;
}) {
  const [phase, setPhase] = useState<RunNowPhase>(initialPhase);
  const [message, setMessage] = useState<string | null>(initialMessage);
  const [text, setText] = useState(record.runNow.needsInput ? inputTemplateText(record.runNow.inputNames) : "");
  const [problem, setProblem] = useState<string | null>(null);

  if (!record.runNow.available) {
    return (
      <p className="news-desk-delegation-note" data-automation-run-now-unavailable>
        Run now is not available: {record.runNow.reason === "disabled" ? "the automation is disabled. Enable it first." : (record.runNow.reason ?? "not supported")}.
      </p>
    );
  }

  async function confirm() {
    const parsed = parseRunInput(text);
    if (!parsed.ok) {
      setProblem(parsed.message);
      return;
    }
    if (record.runNow.needsInput && parsed.value === null) {
      setProblem("This automation's input names an item, so give the input for this run.");
      return;
    }
    setProblem(null);
    setPhase("running");
    try {
      const result = onRun ? await onRun(record.id, parsed.value) : ({ state: "unavailable" } as RunNowResult);
      setMessage(runNowMessage(result));
    } catch {
      setMessage(runNowMessage({ state: "unavailable" }));
    }
    setPhase("done");
  }

  return (
    <div data-automation-run-now={record.id} data-run-now-phase={phase}>
      {phase === "idle" || phase === "done" ? (
        <button type="button" data-automation-run-now-start onClick={() => { setMessage(null); setPhase("confirming"); }}>
          Run now
        </button>
      ) : null}
      {phase === "confirming" || phase === "running" ? (
        <div role="group" aria-label={`Confirm Run now for ${record.title}`} data-automation-run-now-confirm>
          <p>
            Run <strong>{record.procedureKey}</strong> now? It calls a model, which costs money, and it counts against the
            limit of {record.limits.maxConcurrent ?? "?"} at a time. The run is linked to this automation.
          </p>
          {demo ? <p className="news-desk-delegation-note">This is the demo, so nothing will start.</p> : null}
          <label>
            Input for this run{record.runNow.needsInput ? " (required)" : " (optional; blank uses the record's input)"}
            <textarea rows={4} value={text} onChange={(event) => setText(event.target.value)} disabled={phase === "running"} data-automation-run-now-input />
          </label>
          {problem ? <p role="alert" data-automation-run-now-problem>{problem}</p> : null}
          <button type="button" onClick={() => void confirm()} disabled={phase === "running" || demo} data-automation-run-now-confirm-button>
            {phase === "running" ? "Starting…" : "Confirm: start the run"}
          </button>{" "}
          <button type="button" onClick={() => { setPhase("idle"); setProblem(null); }} disabled={phase === "running"} data-automation-run-now-cancel>
            Cancel
          </button>
        </div>
      ) : null}
      {message ? <p role="status" data-automation-run-now-message>{message}</p> : null}
    </div>
  );
}
