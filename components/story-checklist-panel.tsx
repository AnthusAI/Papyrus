"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Ban, CircleCheck, ListChecks, RotateCcw, SkipForward, X, type LucideIcon } from "lucide-react";
import { IssueCard, IssueIdFormatProvider } from "@kanbus/ui";
import { loadStoryChecklistSteps, saveStoryChecklistStep } from "./story-checklist-client";
import {
  MANUAL_STEP_KEYS,
  STORY_STEP_STATE_PRESENTATION,
  checklistProgressText,
  formatStepTime,
  projectStoryStepIssues,
  stepActorText,
  stepChangeProblem,
  storyStepBoardConfig,
  summarizeStoryChecklist,
  type StoryStepRecord,
  type StoryStepState,
} from "../lib/story-checklist";

type Choice = "done" | "skipped" | "not_applicable";
const CHOICES: { state: Choice; label: string; icon: LucideIcon }[] = [
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
              </div> : <div className="story-checklist-form">
                <label htmlFor={`story-step-text-${step.stepKey}`}>{open === "done" ? "What the review found (required)" : open === "skipped" ? "Why it is skipped (required)" : "Why it does not apply (required)"}</label>
                <textarea id={`story-step-text-${step.stepKey}`} className="story-checklist-text" rows={3} value={text} onChange={event => setText(event.target.value)} />
                <div className="story-checklist-buttons">
                  <button type="button" className="story-checklist-button" data-step-action="save" disabled={busy} onClick={() => void save(step, open, open === "done" ? { note: text } : { reason: text })}><CircleCheck aria-hidden size={14} />Save</button>
                  <button type="button" className="story-checklist-button" data-step-action="cancel" disabled={busy} onClick={() => choose(step.stepKey, null)}><X aria-hidden size={14} />Cancel</button>
                </div>
              </div>}
              {problem?.stepKey === step.stepKey ? <p role="alert" className="story-checklist-note" data-step-problem>{problem.message}</p> : null}
            </div>
          </li>;
        })}
      </ol>
    </IssueIdFormatProvider> : null}
  </section>;
}
