/**
 * An editor's research assignment on a Story, built in the browser. It stores the same records as `papyrus stories assign-research` (`stories_commands.py`
 * and `create_research_assignment` in `assignments_workflow.py`): an Assignment of type `research.multi` that names the Story and its section, the first
 * AssignmentEvent, and the editor's direction.
 *
 * The Assignment model has no `metadata`, `brief` or `instructions` columns. The metadata, which holds the `direction` and the `reporter` context profile that
 * the reporting agent's context pack and the research run read, and the instructions text are ModelAttachments owned by the Assignment
 * (`assignment_metadata` in `assignments.py` reads them back). PR 1110 was a live bug from writing them as columns. `buildResearchAssignmentPlan` therefore
 * keeps the row, the event and the two payloads apart, and `features_backend/fixtures/browser-assign-research.json` records what it produces, so a Python test
 * can build the pack from it.
 */
export const RESEARCH_ASSIGNMENT_TYPE = "research.multi";
export const RESEARCH_CONTEXT_PROFILE = "reporter";
export const RESEARCH_MODE = "source_discovery";

/** The words the Work section shows for an assignment's status. The status word is stored; the label and the icon name are for people. */
export type AssignmentStateView = { state: "waiting" | "running" | "finished" | "failed" | "other"; label: string };

export function assignmentStateView(status: string | null | undefined): AssignmentStateView {
  switch (status) {
    case "open": return { state: "waiting", label: "Waiting for the research worker" };
    case "claimed": return { state: "running", label: "Running" };
    case "completed": return { state: "finished", label: "Finished" };
    case "failed": return { state: "failed", label: "Failed" };
    default: return { state: "other", label: status ? status.replace(/_/g, " ") : "Unknown" };
  }
}

export type ResearchAssignmentInput = {
  lineageId: string;
  storyTitle: string;
  /** The Story's section when it is a real section of the site, else null (the CLI leaves the section out in the same case). */
  sectionKey: string | null;
  stage: string | null;
  direction: string;
  actorLabel: string;
  now: Date;
};

export type ResearchAssignmentPlan = {
  assignment: Record<string, unknown> & { id: string };
  event: Record<string, unknown> & { id: string };
  /** The `metadata` ModelAttachment payload. */
  metadata: Record<string, unknown>;
  /** The `assignment_instructions` ModelAttachment payload: the direction text. */
  instructions: string;
  /** A Story at the idea stage moves to the assignment stage once the records are written, as the CLI does. */
  movesStoryToAssignment: boolean;
};

/** The reason a direction cannot be sent, or null. An empty direction is refused: the research would have nothing to go on. */
export function directionProblem(direction: string): string | null {
  return direction.trim() ? null : "Write what the research should find out before you send it.";
}

function safeId(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 140);
  return normalized || "story";
}

function timestampForPath(iso: string): string {
  return [...iso].filter(character => /[0-9TZ]/.test(character)).join("");
}

export function buildResearchAssignmentPlan(input: ResearchAssignmentInput): ResearchAssignmentPlan {
  const direction = input.direction.trim();
  if (!direction) throw new Error(directionProblem(input.direction) ?? "A direction is required.");
  const now = input.now.toISOString();
  const title = input.storyTitle.trim() || "Untitled Story";
  const queueKey = `research:${input.sectionKey ?? "unsectioned"}:exploratory`;
  const id = `assignment-research-${safeId(title).slice(0, 80)}-${timestampForPath(now)}`;
  const status = "open";
  const assignment = {
    id,
    assignmentTypeKey: RESEARCH_ASSIGNMENT_TYPE,
    queueKey,
    queueStatusKey: `${queueKey}#${status}`,
    status,
    priority: 50,
    title,
    summary: title,
    sectionId: input.sectionKey,
    sectionKey: input.sectionKey,
    sectionStatusKey: input.sectionKey ? `${input.sectionKey}#${status}` : null,
    sectionQueueStatusKey: input.sectionKey ? `${input.sectionKey}#${queueKey}#${status}` : null,
    topicScopeCategoryKeys: [] as string[],
    createdBy: input.actorLabel,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: `assignment#${status}`,
    itemLineageId: input.lineageId,
  };
  const event = {
    id: `assignment-event-${id}-created`,
    assignmentId: id,
    assignmentTypeKey: RESEARCH_ASSIGNMENT_TYPE,
    queueKey,
    eventType: "created",
    fromStatus: null,
    toStatus: status,
    actorLabel: input.actorLabel,
    note: `Created research assignment: ${title}`,
    createdAt: now,
  };
  const metadata = {
    kind: "research.assignment.created",
    researchMode: RESEARCH_MODE,
    sectionKey: input.sectionKey,
    topicScopeCategoryKeys: [] as string[],
    contextProfile: RESEARCH_CONTEXT_PROFILE,
    direction,
    createdBy: "newsroom",
    researchBackend: "multi_search",
  };
  return { assignment, event, metadata, instructions: direction, movesStoryToAssignment: input.stage === "idea" };
}
