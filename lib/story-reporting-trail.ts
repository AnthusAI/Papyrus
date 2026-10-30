/**
 * Everything the reporting process recorded about one story, gathered by the story's lineage id:
 * the draft versions of the copy, the research, reporting and copywriting assignments with their events,
 * the notes and packets in the threads anchored to the story or its assignments, the references it draws on,
 * and attached files. See docs/content-item-lifecycle.md for how these records join.
 */
export type TrailVersion = {
  id: string;
  versionNumber: number;
  versionState: string | null;
  status: string | null;
  stage: string | null;
  headline: string | null;
  changeReason: string | null;
  versionCreatedBy: string | null;
  versionCreatedAt: string | null;
  updatedAt: string | null;
};

/** One stage move of the story, read from the latest Item version's `metadata.stageMoves` (not from Messages). */
export type TrailStageMove = {
  at: string;
  from: string | null;
  to: string;
  by: string | null;
  reason: string | null;
};

export type TrailAssignmentEvent = {
  id: string;
  eventType: string;
  fromStatus: string | null;
  toStatus: string | null;
  actorLabel: string | null;
  note: string | null;
  createdAt: string;
};

export type TrailAssignment = {
  id: string;
  title: string;
  assignmentTypeKey: string;
  status: string;
  assigneeKey: string | null;
  summary: string | null;
  createdAt: string;
  events: TrailAssignmentEvent[];
};

export type TrailMessage = {
  id: string;
  sequenceNumber?: number | null;
  messageKind: string | null;
  authorLabel: string | null;
  summary: string | null;
  content: string | null;
  createdAt: string;
};

export type TrailThread = {
  id: string;
  title: string | null;
  threadKind: string | null;
  summary: string | null;
  messages: TrailMessage[];
};

export type TrailReference = {
  relationId: string;
  predicate: string;
  referenceId: string;
  referenceLineageId: string | null;
  title: string | null;
  sourceUri: string | null;
  /** based_on: the story is made from this Reference; consulted: read during reporting; cited: a citation in the article. */
  role: "based_on" | "consulted" | "cited";
  /** The site that published the Reference (its preview's site name, else the host of its address). */
  siteName: string | null;
  /** The Reference's preview image address. It is shown from its own site, never copied. */
  previewImageUrl: string | null;
  note: string | null;
  citationKey: string | null;
  addedBy: string | null;
  addedAt: string | null;
};

export type TrailAttachment = {
  id: string;
  role: string | null;
  filename: string | null;
  mediaType: string | null;
  byteSize: number | null;
};

export type StoryReportingTrail = {
  versions: TrailVersion[];
  assignments: TrailAssignment[];
  threads: TrailThread[];
  references: TrailReference[];
  attachments: TrailAttachment[];
  stageMoves: TrailStageMove[];
};

export const EMPTY_STORY_REPORTING_TRAIL: StoryReportingTrail = { versions: [], assignments: [], threads: [], references: [], attachments: [], stageMoves: [] };

/** The stage moves recorded on an Item version's metadata, oldest first. Anything that is not a well-formed move is skipped. */
export function stageMovesOf(metadata: unknown): TrailStageMove[] {
  let parsed: unknown = metadata;
  if (typeof metadata === "string") {
    try { parsed = JSON.parse(metadata); } catch { return []; }
  }
  const moves = typeof parsed === "object" && parsed ? (parsed as Record<string, unknown>).stageMoves : null;
  if (!Array.isArray(moves)) return [];
  return moves.flatMap(entry => {
    if (typeof entry !== "object" || !entry) return [];
    const move = entry as Record<string, unknown>;
    if (typeof move.at !== "string" || typeof move.to !== "string") return [];
    return [{ at: move.at, from: typeof move.from === "string" ? move.from : null, to: move.to, by: typeof move.by === "string" ? move.by : null, reason: typeof move.reason === "string" ? move.reason : null }];
  });
}

export function storyReportingTrailIsEmpty(trail: StoryReportingTrail): boolean {
  return trail.assignments.length === 0 && trail.threads.length === 0 && trail.stageMoves.length === 0 && trail.references.length === 0 && trail.attachments.length === 0 && trail.versions.length <= 1;
}

export type StoryFeedEntry =
  | ({ entryKind: "message"; threadTitle: string | null } & TrailMessage)
  | { entryKind: "reference"; id: string; createdAt: string; reference: TrailReference };

/** Every message of the story's threads and every reference found for it in one chronological feed, newest first. */
export function storyMessageFeed(trail: StoryReportingTrail): StoryFeedEntry[] {
  const messages: StoryFeedEntry[] = trail.threads.flatMap(thread => thread.messages.map(message => ({ ...message, entryKind: "message" as const, threadTitle: thread.title })));
  const references: StoryFeedEntry[] = trail.references.filter(reference => reference.addedAt).map(reference => ({ entryKind: "reference" as const, id: `reference-${reference.relationId}`, createdAt: reference.addedAt as string, reference }));
  const sequenceOf = (entry: StoryFeedEntry) => (entry.entryKind === "message" ? entry.sequenceNumber ?? 0 : 0);
  return [...messages, ...references].sort((left, right) => right.createdAt.localeCompare(left.createdAt) || sequenceOf(right) - sequenceOf(left));
}

const ROLE_ORDER = { based_on: 0, cited: 1, consulted: 2 } as const;

/** The References of a story, the ones it is based on first. */
export function referencesByRole(references: readonly TrailReference[]): TrailReference[] {
  return [...references].sort((left, right) => ROLE_ORDER[left.role] - ROLE_ORDER[right.role]);
}

export function referenceRoleLabel(role: TrailReference["role"]): string {
  return role === "based_on" ? "Based on" : role === "cited" ? "Cited" : "Consulted";
}

/** A story that a Reference supports, as the Reference view lists it. */
export type ReferenceStory = {
  relationId: string;
  itemId: string;
  lineageId: string;
  title: string | null;
  stage: string | null;
  role: TrailReference["role"];
};

export function siteNameOf(sourceUri: string | null | undefined, preferred?: string | null): string | null {
  if (preferred) return preferred;
  if (!sourceUri) return null;
  try { return new URL(sourceUri).hostname.replace(/^www\./, ""); } catch { return null; }
}
