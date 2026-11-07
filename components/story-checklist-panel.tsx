"use client";

import { useEffect, useMemo, useState } from "react";
import { Ban, Circle, CircleCheck, ListChecks, SkipForward, type LucideIcon } from "lucide-react";
import { loadStoryChecklistSteps } from "./news-desk-taxonomy-client";
import {
  STORY_STEP_STATE_PRESENTATION,
  formatStepTime,
  projectStoryStepIssues,
  stepActorText,
  storyChecklistSummary,
  summarizeStoryChecklist,
  checklistProgressText,
  type StoryStepRecord,
  type StoryStepState,
} from "../lib/story-checklist";

/** Lucide icons only. Every state has an icon and a word, so no state is told by colour alone. */
const STATE_ICONS: Record<StoryStepState, LucideIcon> = { open: Circle, done: CircleCheck, skipped: SkipForward, not_applicable: Ban };

/**
 * The Story's editorial checklist, shown in its panel as Kanbus sub-tasks: each step has a state (icon and word), who changed it and when, the reason or findings
 * note, and, while it is open, the command that closes it. The steps are read by the Story's lineage when the panel opens, never for a card.
 */
export function StoryChecklistPanel({ lineageId, storyIssueId }: { lineageId: string; storyIssueId: string }) {
  const [steps, setSteps] = useState<StoryStepRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setSteps(null); setError(null);
    loadStoryChecklistSteps(lineageId).then(
      loaded => { if (current) setSteps(loaded); },
      reason => { if (current) setError(reason instanceof Error ? reason.message : "Could not load the checklist."); },
    );
    return () => { current = false; };
  }, [lineageId]);
  const subTasks = useMemo(() => projectStoryStepIssues(storyIssueId, steps ?? []), [steps, storyIssueId]);
  const progress = useMemo(() => steps?.length ? checklistProgressText(summarizeStoryChecklist(steps, [], 0)) : null, [steps]);
  return <section className="story-checklist" data-story-checklist aria-labelledby="story-checklist-heading">
    <h3 id="story-checklist-heading" className="story-checklist-heading"><ListChecks aria-hidden size={16} /> Checklist{progress ? <span className="story-checklist-progress">{progress}</span> : null}</h3>
    {error ? <p role="alert" className="story-checklist-note">{error}</p> : null}
    {!error && steps === null ? <p className="story-checklist-note" aria-busy="true">Loading the checklist.</p> : null}
    {steps && !steps.length ? <p className="story-checklist-note">This Story has no checklist yet. It gets one the next time it changes.</p> : null}
    {subTasks.length ? <ol className="story-checklist-steps">
      {subTasks.map(issue => {
        const { step } = issue;
        const presentation = STORY_STEP_STATE_PRESENTATION[step.state];
        const Icon = STATE_ICONS[step.state];
        const who = stepActorText(step);
        const when = formatStepTime(step.changedAt);
        const detail = step.reason || step.note;
        return <li key={issue.id} className="story-checklist-step" data-issue-type={issue.type} data-parent={issue.parent} data-step-state={step.state} data-step-key={step.stepKey}>
          <span className="story-checklist-state"><Icon aria-hidden size={16} /><span>{presentation.label}</span></span>
          <span className="story-checklist-title">{issue.title}</span>
          {who || when ? <span className="story-checklist-meta">{[who, when].filter(Boolean).join(" · ")}</span> : null}
          {detail ? <span className="story-checklist-detail">{step.reason ? "Reason: " : "Findings: "}{detail}</span> : null}
          {step.state === "open" && step.command ? <span className="story-checklist-command">Next: <code>{step.command}</code></span> : null}
        </li>;
      })}
    </ol> : null}
  </section>;
}

export { storyChecklistSummary };
