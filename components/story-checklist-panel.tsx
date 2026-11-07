"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Ban, ChevronDown, ChevronUp, CircleCheck, ListChecks, MessageSquarePlus, RotateCcw, SkipForward, X, type LucideIcon } from "lucide-react";
import { IssueCard, IssueIdFormatProvider } from "@kanbus/ui";
import { addStoryChecklistNote, loadStoryChecklistSteps, saveStoryChecklistStep } from "./story-checklist-client";
import {
  MANUAL_STEP_KEYS,
  VISIBLE_STEP_NOTES,
  noteProblem,
  STORY_STEP_STATE_PRESENTATION,
  checklistProgressText,
  formatStepTime,
  projectStoryStepIssues,
  stepActorText,
  stepChangeProblem,
  storyStepBoardConfig,
  summarizeStoryChecklist,
  type StoryStepNote,
  type StoryStepRecord,
  type StoryStepState,
} from "../lib/story-checklist";

type Choice = "done" | "skipped" | "not_applicable" | "note";
const CHOICES: { state: Exclude<Choice, "note">; label: string; icon: LucideIcon }[] = [
  { state: "done", label: "Mark done", icon: CircleCheck },
  { state: "skipped", label: "Skip", icon: SkipForward },
  { state: "not_applicable", label: "Not applicable", icon: Ban },
];
const STEP_CONFIG = storyStepBoardConfig();
const stepIdText = (issue: { id: string }) => (issue as { step?: StoryStepRecord }).step?.stepKey ?? issue.id;

/**
 * The Story's editorial checklist, shown in its panel as Kanbus sub-tasks: Kanbus's own cards (`type: "sub-task"`, `parent` the Story's card) in its list view, each with its
 * state as a word and an icon, who changed it and when, and the reason or findings. Under every step are the buttons a person can use: mark it done (a review step needs
 * a short note of what it found), skip it or mark it not applicable (each needs a reason), or reopen it. The steps are read by the Story when the panel opens, never for a
 * card. The commands an agent runs live in the CLI and the agent's context, not here.
 */
export function StoryChecklistPanel({ lineageId, storyIssueId, onChanged }: { lineageId: string; storyIssueId: string; onChanged?: () => void }) {
  const [steps, setSteps] = useState<StoryStepRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ stepKey: string; choice: Choice } | null>(null);
  const [text, setText] = useState("");
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ stepKey: string; message: string } | null>(null);
  const load = useCallback(() => loadStoryChecklistSteps(lineageId).then(setSteps, reason => setError(reason instanceof Error ? reason.message : "Could not load the checklist.")), [lineageId]);
  useEffect(() => { setSteps(null); setError(null); setEditing(null); void load(); }, [load]);
  const subTasks = useMemo(() => projectStoryStepIssues(storyIssueId, steps ?? []), [steps, storyIssueId]);
  const progress = useMemo(() => steps?.length ? checklistProgressText(summarizeStoryChecklist(steps, [], 0)) : null, [steps]);
  const choose = (stepKey: string, choice: Choice | null) => { setEditing(choice ? { stepKey, choice } : null); setText(""); setProblem(null); };
  const save = async (step: StoryStepRecord, state: StoryStepState, input: { reason?: string; note?: string }) => {
    const found = stepChangeProblem(step.stepKey, state, input);
    if (found) { setProblem({ stepKey: step.stepKey, message: found }); return; }
    setSavingKey(step.stepKey); setProblem(null);
    try {
      await saveStoryChecklistStep(lineageId, step.stepKey, state, input);
      choose(step.stepKey, null);
      await load();
      onChanged?.();
    } catch (reason) {
      setProblem({ stepKey: step.stepKey, message: reason instanceof Error ? reason.message : "The change could not be saved." });
    } finally { setSavingKey(null); }
  };
  const saveNote = async (step: StoryStepRecord) => {
    const found = noteProblem(text);
    if (found) { setProblem({ stepKey: step.stepKey, message: found }); return; }
    setSavingKey(step.stepKey); setProblem(null);
    try {
      await addStoryChecklistNote(lineageId, step.stepKey, text);
      choose(step.stepKey, null);
      setExpandedNotes(current => new Set(current).add(step.stepKey));
      await load();
      onChanged?.();
    } catch (reason) {
      setProblem({ stepKey: step.stepKey, message: reason instanceof Error ? reason.message : "The note could not be saved." });
    } finally { setSavingKey(null); }
  };
  return <section className="story-checklist" data-story-checklist aria-labelledby="story-checklist-heading">
    <h3 id="story-checklist-heading" className="story-checklist-heading"><ListChecks aria-hidden size={16} /> Checklist{progress ? <span className="story-checklist-progress">{progress}</span> : null}</h3>
    {error ? <p role="alert" className="story-checklist-note">{error}</p> : null}
    {!error && steps === null ? <p className="story-checklist-note" aria-busy="true">Loading the checklist.</p> : null}
    {steps && !steps.length ? <p className="story-checklist-note">This Story has no checklist yet. It gets one the next time it changes.</p> : null}
    {subTasks.length ? <IssueIdFormatProvider formatIssueId={stepIdText}>
      <ol className="story-checklist-steps">
        {subTasks.map(issue => {
          const step = issue.step;
          const busy = savingKey === step.stepKey;
          const open = editing?.stepKey === step.stepKey ? editing.choice : null;
          return <li key={issue.id} className="story-checklist-step" data-step-key={step.stepKey}>
            <IssueCard issue={issue} priorityName={STORY_STEP_STATE_PRESENTATION[step.state].label} config={STEP_CONFIG} motion={{ mode: "static" }} />
            <div className="story-checklist-actions" data-story-step-actions={step.stepKey}>
              {open === null ? <div className="story-checklist-buttons">
                {step.state === "open"
                  ? CHOICES.map(({ state, label, icon: Icon }) => <button key={state} type="button" className="story-checklist-button" data-step-action={state} disabled={busy}
                      onClick={() => state === "done" && !MANUAL_STEP_KEYS.includes(step.stepKey) ? void save(step, "done", {}) : choose(step.stepKey, state)}><Icon aria-hidden size={14} />{label}</button>)
                  : <button type="button" className="story-checklist-button" data-step-action="open" disabled={busy} onClick={() => void save(step, "open", {})}><RotateCcw aria-hidden size={14} />Reopen</button>}
                <button type="button" className="story-checklist-button" data-step-action="note" disabled={busy} onClick={() => choose(step.stepKey, "note")}><MessageSquarePlus aria-hidden size={14} />Add note</button>
              </div> : <div className="story-checklist-form">
                <label htmlFor={`story-step-text-${step.stepKey}`}>{open === "note" ? "Your note, for whoever works on this Story next" : open === "done" ? "What the review found (required)" : open === "skipped" ? "Why it is skipped (required)" : "Why it does not apply (required)"}</label>
                <textarea id={`story-step-text-${step.stepKey}`} className="story-checklist-text" rows={3} value={text} onChange={event => setText(event.target.value)} />
                <div className="story-checklist-buttons">
                  <button type="button" className="story-checklist-button" data-step-action="save" disabled={busy} onClick={() => void (open === "note" ? saveNote(step) : save(step, open, open === "done" ? { note: text } : { reason: text }))}><CircleCheck aria-hidden size={14} />Save</button>
                  <button type="button" className="story-checklist-button" data-step-action="cancel" disabled={busy} onClick={() => choose(step.stepKey, null)}><X aria-hidden size={14} />Cancel</button>
                </div>
              </div>}
              {problem?.stepKey === step.stepKey ? <p role="alert" className="story-checklist-note" data-step-problem>{problem.message}</p> : null}
            </div>
            {step.notes.length ? <StepNotes notes={step.notes} expanded={expandedNotes.has(step.stepKey)} onToggle={() => setExpandedNotes(current => { const next = new Set(current); if (!next.delete(step.stepKey)) next.add(step.stepKey); return next; })} /> : null}
          </li>;
        })}
      </ol>
    </IssueIdFormatProvider> : null}
  </section>;
}

/** The notes left on a step, oldest first so the newest is last and nearest the buttons. More than a few are folded: the newest stay visible and the rest open on request. */
function StepNotes({ notes, expanded, onToggle }: { notes: StoryStepNote[]; expanded: boolean; onToggle: () => void }) {
  const folded = !expanded && notes.length > VISIBLE_STEP_NOTES;
  const shown = folded ? notes.slice(-VISIBLE_STEP_NOTES) : notes;
  const hidden = notes.length - shown.length;
  return <div className="story-checklist-notes" data-step-notes={notes.length}>
    {notes.length > VISIBLE_STEP_NOTES ? <button type="button" className="story-checklist-button story-checklist-fold" data-step-notes-toggle aria-expanded={!folded} onClick={onToggle}>
      {folded ? <ChevronDown aria-hidden size={14} /> : <ChevronUp aria-hidden size={14} />}{folded ? `Show ${hidden} earlier note${hidden === 1 ? "" : "s"}` : "Show only the newest notes"}</button> : null}
    <ol className="story-checklist-note-list">
      {shown.map((note, index) => <li key={`${note.at}-${index}`} className="story-checklist-note-item" data-step-note>
        <span className="story-checklist-note-text">{note.text}</span>
        <span className="story-checklist-meta">{[note.actorLabel ? `${note.actorLabel}${note.actorKind === "agent" ? " (agent)" : ""}` : "", formatStepTime(note.at)].filter(Boolean).join(" · ")}</span>
      </li>)}
    </ol>
  </div>;
}
