"use client";

import { AlertCircleIcon, CheckIcon, Loader2Icon, SearchIcon } from "lucide-react";
import { useId, useState } from "react";
import { directionProblem, RESEARCH_RUN_NOTE } from "../lib/assign-research";
import { assignResearch } from "./assign-research-client";

/**
 * "Assign research" on a Story, at every stage: the editor writes what the research should find out and sends it. The research assignment is the one
 * `papyrus stories assign-research` makes; a worker runs it without anyone at a terminal, and the Work section below shows it from "waiting" to its packet.
 * One textarea and one button; an empty direction is refused here, in words, before anything is written.
 */
export function AssignResearchBox({ demo = false, lineageId, onAssigned, sectionKey, stage, storyTitle }: { demo?: boolean; lineageId: string; onAssigned: () => void; sectionKey: string | null; stage: string | null; storyTitle: string }) {
  const [direction, setDirection] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const textareaId = useId();

  async function send() {
    if (busy) return;
    const refused = directionProblem(direction);
    setDone(null);
    if (refused) { setProblem(refused); return; }
    setProblem(null);
    setBusy(true);
    try {
      const result = await assignResearch({ demo, direction, lineageId, sectionKey, stage, storyTitle });
      setDirection("");
      setDone(demo
        ? "Research assigned. In the preview no worker runs, so it stays waiting."
        : `Research assigned. The research worker picks it up within minutes.${result.movedStory ? " The Story moved to the assignment stage." : ""}`);
      onAssigned();
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "The research could not be assigned.");
      onAssigned();
    } finally {
      setBusy(false);
    }
  }

  return <div className="assign-research" data-assign-research>
    <textarea
      aria-label="What should the research find out?"
      aria-describedby={problem ? `${textareaId}-problem` : undefined}
      aria-invalid={problem ? true : undefined}
      className="assign-research-text"
      data-assign-research-direction
      id={textareaId}
      onChange={event => { setDirection(event.target.value); if (problem) setProblem(null); }}
      placeholder="What should the research find out? For example: find other cases like this one, and where the sources disagree."
      rows={4}
      value={direction}
    />
    <p className="assign-research-note" data-assign-research-explains>{RESEARCH_RUN_NOTE}</p>
    <div className="assign-research-actions">
      <button aria-busy={busy || undefined} className="assign-research-button" data-assign-research-send disabled={busy} onClick={() => void send()} type="button">
        {busy ? <Loader2Icon aria-hidden="true" className="assign-research-spin" size={15} /> : <SearchIcon aria-hidden="true" size={15} />}
        {busy ? "Assigning…" : "Assign research"}
      </button>
    </div>
    {problem && <p className="assign-research-note assign-research-problem" data-assign-research-problem id={`${textareaId}-problem`} role="alert"><AlertCircleIcon aria-hidden="true" size={14} /> {problem}</p>}
    {done && <p className="assign-research-note" data-assign-research-done role="status"><CheckIcon aria-hidden="true" size={14} /> {done}</p>}
  </div>;
}
