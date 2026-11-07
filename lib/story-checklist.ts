import type { KanbanIssue } from "@kanbus/ui";

/** The editorial checklist of one Story (docs/story-procedure.md, "The checklist"). Mirrors src/papyrus_content/story_checklist.py. */
export const STORY_STEP_STATES = ["open", "done", "skipped", "not_applicable"] as const;
export type StoryStepState = (typeof STORY_STEP_STATES)[number];

/** The kind of the Kanbus issue each checklist item is shown as: a sub-task of the Story's card. */
export const STORY_STEP_ISSUE_TYPE = "sub-task";

/** The small summary kept on the Story's current version (`metadata.checklist`), so a board card needs no extra query. */
export interface StoryChecklistSummary {
  templateVersion: number;
  total: number;
  open: number;
  done: number;
  skipped: number;
  not_applicable: number;
  requiredOpen: string[];
}

export interface StoryStepRecord {
  id: string;
  storyLineageId: string;
  stepKey: string;
  stepOrder: number;
  templateVersion: number;
  title?: string | null;
  command?: string | null;
  state: StoryStepState;
  actorKind?: string | null;
  actorLabel?: string | null;
  changedAt?: string | null;
  reason?: string | null;
  note?: string | null;
  evidence?: string | null;
}

/** A state is never shown by colour alone: each has a label and an icon name (a Lucide icon). */
export const STORY_STEP_STATE_PRESENTATION: Record<StoryStepState, { label: string; icon: "Circle" | "CircleCheck" | "SkipForward" | "Ban" }> = {
  open: { label: "Open", icon: "Circle" },
  done: { label: "Done", icon: "CircleCheck" },
  skipped: { label: "Skipped", icon: "SkipForward" },
  not_applicable: { label: "Not applicable", icon: "Ban" },
};

function metadataObject(metadata: unknown): Record<string, unknown> | null {
  if (typeof metadata === "string") {
    try { return metadataObject(JSON.parse(metadata)); } catch { return null; }
  }
  return metadata && typeof metadata === "object" && !Array.isArray(metadata) ? (metadata as Record<string, unknown>) : null;
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** The checklist summary a Story's version metadata carries; null for a Story with no checklist yet. */
export function storyChecklistSummary(metadata: unknown): StoryChecklistSummary | null {
  const raw = metadataObject(metadata)?.checklist;
  const summary = metadataObject(raw);
  if (!summary || !count(summary.total)) return null;
  return {
    templateVersion: count(summary.templateVersion), total: count(summary.total), open: count(summary.open), done: count(summary.done),
    skipped: count(summary.skipped), not_applicable: count(summary.not_applicable),
    requiredOpen: Array.isArray(summary.requiredOpen) ? summary.requiredOpen.filter((key): key is string => typeof key === "string") : [],
  };
}

/** The card line, for example `4/9 · 2 skipped`: done and not-applicable steps over all steps, then the skipped count. */
export function checklistProgressText(summary: StoryChecklistSummary): string {
  const answered = summary.done + summary.not_applicable;
  return `${answered}/${summary.total}${summary.skipped ? ` · ${summary.skipped} skipped` : ""}`;
}

/** The full sentence for assistive technology and the tooltip. */
export function checklistProgressLabel(summary: StoryChecklistSummary): string {
  const parts = [`${summary.done} done`, `${summary.not_applicable} not applicable`, `${summary.skipped} skipped`, `${summary.open} open`];
  return `Checklist: ${checklistProgressText(summary)} (${parts.join(", ")})`;
}

/** Each stored step as a Kanbus sub-task of the Story's card: type `sub-task`, parent the Story's issue id, status the step state. */
export function projectStoryStepIssues(storyIssueId: string, steps: readonly StoryStepRecord[]): (KanbanIssue & { step: StoryStepRecord })[] {
  return [...steps].sort((a, b) => a.stepOrder - b.stepOrder).map(step => ({
    id: `storyStep:${step.id}`, title: step.title || step.stepKey, type: STORY_STEP_ISSUE_TYPE, status: step.state, priority: 2,
    parent: storyIssueId, assignee: step.actorLabel || undefined, updated_at: step.changedAt || undefined, step,
  }));
}

/** The counts of a list of steps: what the backend keeps on the Story, and what the preview fixtures carry. */
export function summarizeStoryChecklist(steps: readonly StoryStepRecord[], requiredKeys: readonly string[], templateVersion: number): StoryChecklistSummary {
  const counted = (state: StoryStepState) => steps.filter(step => step.state === state).length;
  return {
    templateVersion, total: steps.length, open: counted("open"), done: counted("done"), skipped: counted("skipped"), not_applicable: counted("not_applicable"),
    requiredOpen: steps.filter(step => step.state === "open" && requiredKeys.includes(step.stepKey)).map(step => step.stepKey),
  };
}

const STEP_TIME = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });

/** When a step last changed, in UTC so it reads the same for everyone. */
export function formatStepTime(iso: string | null | undefined): string {
  const parsed = iso ? new Date(iso) : null;
  return parsed && !Number.isNaN(parsed.getTime()) ? `${STEP_TIME.format(parsed)} UTC` : "";
}

/** The words that say who changed a step: `Ryan`, `AI (agent)`, or `evidence` for a step the records proved. */
export function stepActorText(step: Pick<StoryStepRecord, "actorKind" | "actorLabel">): string {
  if (!step.actorLabel) return "";
  if (step.actorKind === "system") return step.actorLabel;
  return step.actorKind === "agent" ? `${step.actorLabel} (agent)` : step.actorLabel;
}
