import type { KanbanConfig, KanbanIssue } from "@kanbus/ui";

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

/** One note left on a step, for context later: who (a person or an agent, by name), when, and the text. Notes only accumulate; newest last. */
export interface StoryStepNote {
  at: string;
  actorKind?: string | null;
  actorLabel?: string | null;
  text: string;
}

/** How many of a step's notes show at once; older ones sit behind "Show earlier notes". */
export const VISIBLE_STEP_NOTES = 3;

/** One checklist step as the panel shows it: the newest version of the step's sub-task Item, with the entry of each version as its history. */
export interface StoryStepRecord {
  /** The step's lineage id (`step-<story>-<key>`): the sub-task Item's `lineageId`. */
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
  /** The log of notes people and agents left on the step, newest last. */
  notes: StoryStepNote[];
}

/** The fields of a sub-task Item the panel reads (`listItemsByParentAndOrder`). Every version of every step comes back; the newest version of each is the step. */
export interface SubTaskItemRecord {
  id: string;
  lineageId: string;
  versionNumber: number;
  type: string;
  status: string;
  title?: string | null;
  parentLineageId?: string | null;
  versionCreatedAt?: string | null;
  metadata?: unknown;
}

/** The steps whose done needs a short findings note (the four review lenses); mirrors `manual` in src/papyrus_content/newsroom_process.py. */
export const MANUAL_STEP_KEYS: readonly string[] = ["review_people", "review_reader_agents", "review_search", "review_social"];

/** What an editor must give for a change, the same rules the backend enforces (src/papyrus_content/story_checklist.py): a reason to skip or mark not applicable, findings to mark a review done. */
export function stepChangeProblem(stepKey: string, state: StoryStepState, input: { reason?: string; note?: string }): string | null {
  if ((state === "skipped" || state === "not_applicable") && !input.reason?.trim()) return `Say why the step is ${state === "skipped" ? "skipped" : "not applicable"}.`;
  if (state === "done" && MANUAL_STEP_KEYS.includes(stepKey) && !input.note?.trim()) return "Write a short note of what the review found.";
  return null;
}

/** The notes of a step from `metadata.checklist.notes`: the entries that have text, in the order stored (newest last). */
export function storyStepNotes(value: unknown): StoryStepNote[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry): StoryStepNote[] => {
    const note = metadataObject(entry);
    const text = typeof note?.text === "string" ? note.text : "";
    return note && text ? [{ at: typeof note.at === "string" ? note.at : "", actorKind: typeof note.actorKind === "string" ? note.actorKind : null, actorLabel: typeof note.actorLabel === "string" ? note.actorLabel : null, text }] : [];
  });
}

/** What a person must give to add a note: some text. */
export function noteProblem(text: string): string | null {
  return text.trim() ? null : "Write the note first.";
}

/** The steps of a Story from its sub-task Items: the newest version of each is the step, in template order. */
export function storyStepsFromItems(items: readonly SubTaskItemRecord[]): StoryStepRecord[] {
  const newest = new Map<string, SubTaskItemRecord>();
  for (const item of items) {
    if (item.type !== STORY_STEP_ISSUE_TYPE) continue;
    const current = newest.get(item.lineageId);
    if (!current || item.versionNumber > current.versionNumber) newest.set(item.lineageId, item);
  }
  return [...newest.values()].map((item): StoryStepRecord => {
    const meta = metadataObject(metadataObject(item.metadata)?.checklist) ?? {};
    const entry = metadataObject(meta.entry) ?? {};
    const text = (value: unknown) => (typeof value === "string" && value ? value : null);
    return {
      id: item.lineageId, storyLineageId: item.parentLineageId ?? "", stepKey: text(meta.stepKey) ?? item.lineageId, stepOrder: count(meta.stepOrder),
      templateVersion: count(meta.templateVersion), title: item.title ?? null, command: text(meta.command), state: item.status as StoryStepState,
      actorKind: text(entry.actorKind), actorLabel: text(entry.actorLabel), changedAt: text(entry.at) ?? item.versionCreatedAt ?? null,
      reason: text(entry.reason), note: text(entry.note), evidence: text(entry.evidence), notes: storyStepNotes(meta.notes),
    };
  }).sort((a, b) => a.stepOrder - b.stepOrder);
}

/** A state is never shown by colour alone: each has a label and an icon name (a Lucide icon). */
export const STORY_STEP_STATE_PRESENTATION: Record<StoryStepState, { label: string; icon: "Circle" | "CircleCheck" | "SkipForward" | "Ban"; priority: number }> = {
  open: { label: "Open", icon: "Circle", priority: 1 },
  done: { label: "Done", icon: "CircleCheck", priority: 2 },
  skipped: { label: "Skipped", icon: "SkipForward", priority: 3 },
  not_applicable: { label: "Not applicable", icon: "Ban", priority: 4 },
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

/** The words an editor reads for who changed a step and when, for the card's owner line. */
function ownerLine(step: StoryStepRecord): string {
  return stepActorText(step);
}

/**
 * Each stored step as a Kanbus sub-task of the Story's card: type `sub-task`, parent the Story's issue id, status the step state, the actor as assignee, the reason or
 * findings as the excerpt, and a priority that names the state, so Kanbus's own cards say Open, Done, Skipped or Not applicable.
 */
export function projectStoryStepIssues(storyIssueId: string, steps: readonly StoryStepRecord[]): (KanbanIssue & { step: StoryStepRecord })[] {
  return [...steps].sort((a, b) => a.stepOrder - b.stepOrder).map(step => ({
    id: `storyStep:${step.id}`, title: step.title || step.stepKey, type: STORY_STEP_ISSUE_TYPE, status: step.state, priority: STORY_STEP_STATE_PRESENTATION[step.state].priority,
    parent: storyIssueId, assignee: ownerLine(step) || undefined, updated_at: step.changedAt || undefined,
    excerpt: step.reason ? `Reason: ${step.reason}` : step.note ? `Findings: ${step.note}` : undefined, step,
  }));
}

/** The Kanbus config for a Story's sub-tasks: one status per state, and a priority per state so each card names its state. */
export function storyStepBoardConfig(): KanbanConfig {
  const statuses = STORY_STEP_STATES.map(state => ({ key: state, name: STORY_STEP_STATE_PRESENTATION[state].label, category: "native" }));
  return {
    hierarchy: [], types: [STORY_STEP_ISSUE_TYPE], statuses, categories: [{ name: "native" }],
    priorities: Object.fromEntries(STORY_STEP_STATES.map(state => [STORY_STEP_STATE_PRESENTATION[state].priority, { name: STORY_STEP_STATE_PRESENTATION[state].label }])),
    type_colors: {}, workflows: { [STORY_STEP_ISSUE_TYPE]: Object.fromEntries(STORY_STEP_STATES.map(state => [state, []])) },
  };
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
