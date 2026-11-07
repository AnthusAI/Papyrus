"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Ban, CircleCheck, ListChecks, RotateCcw, SkipForward, X, type LucideIcon } from "lucide-react";
import { IssueCollection } from "@kanbus/ui";
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
const STEP_QUERY = { type: "sub-task" } as const;
const stepIdText = (issue: { id: string }) => issue.id;

/**
 * The Story's editorial checklist, shown in its panel as Kanbus sub-tasks: Kanbus's own cards (`type: "sub-task"`, `parent` the Story's card) in its list view, each with its
 * state as a word and an icon, who changed it and when, and the reason or findings. Choosing a step offers what a person can do with it: mark it done (a review step needs
 * a short note of what it found), skip it or mark it not applicable (each needs a reason), or reopen it. The steps are read by the Story when the panel opens, never for a
 * card. The commands an agent runs live in the CLI and the agent's context, not here.
 */
export function StoryChecklistPanel({ lineageId, storyIssueId, onChanged }: { lineageId: string; storyIssueId: string; onChanged?: () => void }) {
  const [steps, setSteps] = useState<StoryStepRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const load = useCallback(() => loadStoryChecklistSteps(lineageId).then(setSteps, reason => setError(reason instanceof Error ? reason.message : "Could not load the checklist.")), [lineageId]);
  useEffect(() => { setSteps(null); setError(null); setSelectedId(null); setChoice(null); void load(); }, [load]);
  const subTasks = useMemo(() => projectStoryStepIssues(storyIssueId, steps ?? []), [steps, storyIssueId]);
  const progress = useMemo(() => steps?.length ? checklistProgressText(summarizeStoryChecklist(steps, [], 0)) : null, [steps]);
  const selected = steps?.find(step => `storyStep:${step.id}` === selectedId) ?? null;
  const choose = (next: Choice | null) => { setChoice(next); setText(""); setProblem(null); };
  const save = async (step: StoryStepRecord, state: StoryStepState, input: { reason?: string; note?: string }) => {
    const found = stepChangeProblem(step.stepKey, state, input);
    if (found) { setProblem(found); return; }
    setSaving(true); setProblem(null);
    try {
      await saveStoryChecklistStep(lineageId, step.stepKey, state, input);
      choose(null);
      await load();
      onChanged?.();
    } catch (reason) {
      setProblem(reason instanceof Error ? reason.message : "The change could not be saved.");
    } finally { setSaving(false); }
  };
  const submit = (step: StoryStepRecord, state: Choice) => save(step, state, state === "done" ? { note: text } : { reason: text });
  return <section className="story-checklist" data-story-checklist aria-labelledby="story-checklist-heading">
    <h3 id="story-checklist-heading" className="story-checklist-heading"><ListChecks aria-hidden size={16} /> Checklist{progress ? <span className="story-checklist-progress">{progress}</span> : null}</h3>
    {error ? <p role="alert" className="story-checklist-note">{error}</p> : null}
    {!error && steps === null ? <p className="story-checklist-note" aria-busy="true">Loading the checklist.</p> : null}
    {steps && !steps.length ? <p className="story-checklist-note">This Story has no checklist yet. It gets one the next time it changes.</p> : null}
    {subTasks.length ? <div className="story-checklist-steps">
      <IssueCollection issues={subTasks} config={STEP_CONFIG} query={STEP_QUERY} view="list" selectedIssueId={selectedId} onSelectIssue={issue => { setSelectedId(issue.id); choose(null); }}
        formatIssueId={issue => (issue as { step?: StoryStepRecord }).step?.stepKey ?? stepIdText(issue)} motion={{ mode: "static" }} ariaLabel="Checklist steps" />
    </div> : null}
    {selected ? <div className="story-checklist-actions" data-story-step-actions={selected.stepKey}>
      <p className="story-checklist-actions-title">{selected.title || selected.stepKey}</p>
      <p className="story-checklist-meta">{[STORY_STEP_STATE_PRESENTATION[selected.state].label, stepActorText(selected), formatStepTime(selected.changedAt)].filter(Boolean).join(" · ")}</p>
      {choice === null ? <div className="story-checklist-buttons">
        {selected.state === "open"
          ? CHOICES.map(({ state, label, icon: Icon }) => <button key={state} type="button" className="story-checklist-button" data-step-action={state} disabled={saving}
              onClick={() => state === "done" && !MANUAL_STEP_KEYS.includes(selected.stepKey) ? void save(selected, "done", {}) : choose(state)}><Icon aria-hidden size={14} />{label}</button>)
          : <button type="button" className="story-checklist-button" data-step-action="open" disabled={saving} onClick={() => void save(selected, "open", {})}><RotateCcw aria-hidden size={14} />Reopen</button>}
      </div> : <div className="story-checklist-form">
        <label htmlFor="story-step-text">{choice === "done" ? "What the review found (required)" : choice === "skipped" ? "Why it is skipped (required)" : "Why it does not apply (required)"}</label>
        <textarea id="story-step-text" className="story-checklist-text" rows={3} value={text} onChange={event => setText(event.target.value)} />
        <div className="story-checklist-buttons">
          <button type="button" className="story-checklist-button" data-step-action="save" disabled={saving} onClick={() => void submit(selected, choice)}><CircleCheck aria-hidden size={14} />Save</button>
          <button type="button" className="story-checklist-button" data-step-action="cancel" disabled={saving} onClick={() => choose(null)}><X aria-hidden size={14} />Cancel</button>
        </div>
      </div>}
      {problem ? <p role="alert" className="story-checklist-note" data-step-problem>{problem}</p> : null}
    </div> : steps?.length ? <p className="story-checklist-note">Choose a step to mark it done, skip it, mark it not applicable, or reopen it.</p> : null}
  </section>;
}
