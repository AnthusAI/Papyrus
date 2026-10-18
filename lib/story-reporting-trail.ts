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
  /** consulted: read during reporting; cited: a citation in the article. */
  role: "consulted" | "cited";
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
};

export const EMPTY_STORY_REPORTING_TRAIL: StoryReportingTrail = { versions: [], assignments: [], threads: [], references: [], attachments: [] };

export function storyReportingTrailIsEmpty(trail: StoryReportingTrail): boolean {
  return trail.assignments.length === 0 && trail.threads.length === 0 && trail.references.length === 0 && trail.attachments.length === 0 && trail.versions.length <= 1;
}

/** Every message of the story's threads in one feed, newest first. */
export function storyMessageFeed(trail: StoryReportingTrail): (TrailMessage & { threadTitle: string | null })[] {
  return trail.threads
    .flatMap(thread => thread.messages.map(message => ({ ...message, threadTitle: thread.title })))
    .sort((left, right) => right.createdAt.localeCompare(left.createdAt) || (right.sequenceNumber ?? 0) - (left.sequenceNumber ?? 0));
}
