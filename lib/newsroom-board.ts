import type { KanbanConfig, KanbanIssue } from "@kanbus/ui";
import type { AssignmentRecord } from "./category-repository";
import {
  ASSIGNMENT_PHASE_STAGE_KEYS,
  PUBLISHED_STAGE_KEY,
  canonicalContentItemStage,
  contentItemStageKeys,
  contentItemStageLabel,
  latestVersionPerContentItem,
  type ContentItemVersionRecord,
} from "./content-item-lifecycle";
import { contentItemExcerpt } from "./front-matter-fields";
import { assignmentStatusLabel } from "./newsroom-assignments";
import { getContentItemName, getContentItemStageDefinitions } from "./site-brand";

export type NativeBoardKind = "contentItem" | "assignment";
export interface NativeBoardIssue extends KanbanIssue {
  kind: NativeBoardKind;
  nativeId: string;
  nativeStatus: string;
  href: string;
  /** A few lines to show under the headline: the blurb, else the subtitle. */
  excerpt?: string;
  /** The quiet path shown where a board would print the ID, e.g. `articles/my-slug` or `assignments/write-it`. */
  displayId: string;
}

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

/** Section and slug for a content item, falling back to the publication's board path segment. */
export function contentItemDisplayId(version: { section?: string | null; slug?: string | null; lineageId: string }): string {
  const section = slugify(version.section ?? "") || contentItemBoardPathSegment();
  return `${section}/${slugify(version.slug ?? "") || version.lineageId.slice(0, 8)}`;
}

/** Assignments have no slug: use the title as one, else a short id. */
export function assignmentDisplayId(assignment: { id: string; title?: string | null }): string {
  const titleSlug = slugify(assignment.title ?? "").slice(0, 48).replace(/-+$/g, "");
  return `assignments/${titleSlug || assignment.id.slice(0, 8)}`;
}

/** `formatIssueId` for the Kanbus UI: the host-provided path, never the raw `kind:id` prefix. */
export function formatNativeIssueId(issue: KanbanIssue): string {
  const displayId = (issue as Partial<NativeBoardIssue>).displayId;
  if (displayId) return displayId;
  return issue.id.replace(/^[A-Za-z]+:/, "").slice(0, 12);
}

export function contentItemBoardPathSegment(): string {
  return getContentItemName().plural.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "articles";
}

export function contentItemBoardType(): string {
  return getContentItemName().singular.toLowerCase();
}

export const ASSIGNMENT_BOARD_TYPE = "assignment";

const ASSIGNMENT_STATUSES_BEFORE_OTHERS = ["open", "claimed"];
const ASSIGNMENT_STATUSES_AFTER_OTHERS = ["completed", "canceled"];

/** One card per content item, in the column for its lifecycle stage; its assignments are counted on the card. */
export function projectContentItemBoard(records: {
  contentItemVersions: readonly ContentItemVersionRecord[];
  assignments?: readonly AssignmentRecord[];
}): NativeBoardIssue[] {
  const assignmentCountByContentItem = new Map<string, number>();
  for (const assignment of records.assignments ?? []) {
    if (assignment.itemLineageId) {
      assignmentCountByContentItem.set(assignment.itemLineageId, (assignmentCountByContentItem.get(assignment.itemLineageId) ?? 0) + 1);
    }
  }
  const contentItemType = contentItemBoardType();
  const stageDefinitions = getContentItemStageDefinitions();
  const stageKeys = contentItemStageKeys(stageDefinitions);
  const contentItemVersionsOnBoard = latestVersionPerContentItem(records.contentItemVersions)
    .map(version => ({ version, stage: canonicalContentItemStage(version.stage ?? "idea", stageDefinitions) }))
    .filter(({ stage }) => stageKeys.includes(stage) || !ASSIGNMENT_PHASE_STAGE_KEYS.includes(stage));
  return contentItemVersionsOnBoard.map(({ version, stage }) => {
    const workCount = assignmentCountByContentItem.get(version.lineageId) ?? 0;
    return {
      id: `contentItem:${version.lineageId}`, nativeId: version.lineageId, kind: "contentItem" as const, type: contentItemType,
      title: version.headline || version.title || version.slug, nativeStatus: stage, status: `${contentItemType}/${stage}`,
      priority: 2, description: workCount ? `${workCount} assignment${workCount === 1 ? "" : "s"} on this ${contentItemType}.` : undefined,
      updated_at: version.updatedAt ?? undefined, href: `/newsroom/articles/${encodeURIComponent(version.id)}`,
      excerpt: contentItemExcerpt(version), displayId: contentItemDisplayId(version),
    };
  });
}

/** One card per assignment, in the column for its status. */
export function projectAssignmentBoard(assignments: readonly AssignmentRecord[]): NativeBoardIssue[] {
  return assignments.map(row => ({
    id: `assignment:${row.id}`, nativeId: row.id, kind: "assignment" as const, type: ASSIGNMENT_BOARD_TYPE,
    title: row.title, nativeStatus: row.status, status: `${ASSIGNMENT_BOARD_TYPE}/${row.status}`,
    priority: row.priority ?? 2, assignee: row.assigneeId || undefined,
    description: row.summary || row.brief || undefined,
    created_at: row.createdAt, updated_at: row.updatedAt,
    href: `/newsroom/assignments/${encodeURIComponent(row.id)}`, displayId: assignmentDisplayId(row),
  }));
}

export function contentItemColumnOrder(
  stagesPresentOnBoard: readonly string[],
  stageKeys: readonly string[] = contentItemStageKeys(getContentItemStageDefinitions()),
): string[] {
  const unrecognizedStages = [...new Set(stagesPresentOnBoard)].filter(stage => !stageKeys.includes(stage));
  const stageBeforeWhichUnrecognizedStagesSit = stageKeys.includes(PUBLISHED_STAGE_KEY) ? PUBLISHED_STAGE_KEY : stageKeys[stageKeys.length - 1];
  const insertionIndex = stageKeys.indexOf(stageBeforeWhichUnrecognizedStagesSit);
  return [...stageKeys.slice(0, insertionIndex), ...unrecognizedStages, ...stageKeys.slice(insertionIndex)];
}

export function assignmentColumnOrder(statusesPresentOnBoard: readonly string[]): string[] {
  const knownStatuses = [...ASSIGNMENT_STATUSES_BEFORE_OTHERS, ...ASSIGNMENT_STATUSES_AFTER_OTHERS];
  const otherStatuses = [...new Set(statusesPresentOnBoard)].filter(status => !knownStatuses.includes(status));
  return [...ASSIGNMENT_STATUSES_BEFORE_OTHERS, ...otherStatuses, ...ASSIGNMENT_STATUSES_AFTER_OTHERS];
}

function boardConfigForType(type: string, columns: readonly { key: string; name: string; collapsed?: boolean }[]): KanbanConfig {
  const statuses = columns.map(column => ({ ...column, category: "native" }));
  return {
    hierarchy: [], types: [type], statuses,
    categories: [{ name: "native" }], priorities: {}, type_colors: {},
    workflows: { [type]: Object.fromEntries(statuses.map(status => [status.key, []])) },
  };
}

/** Content items read left to right through the lifecycle; stages marked collapsed-until-opened start collapsed. */
export function contentItemBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  const contentItemType = contentItemBoardType();
  return boardConfigForType(contentItemType, contentItemColumnOrder(issues.map(issue => issue.nativeStatus))
    .map(stage => ({
      key: `${contentItemType}/${stage}`,
      name: contentItemStageLabel(stage, getContentItemStageDefinitions()),
      collapsed: getContentItemStageDefinitions().some(definition => definition.key === stage && definition.collapsedUntilOpened),
    })));
}

export function assignmentBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  return boardConfigForType(ASSIGNMENT_BOARD_TYPE, assignmentColumnOrder(issues.map(issue => issue.nativeStatus))
    .map(status => ({ key: `${ASSIGNMENT_BOARD_TYPE}/${status}`, name: assignmentStatusLabel(status) })));
}

function matchesDesk(candidate: string | null | undefined, deskId: string): boolean {
  return Boolean(candidate) && candidate!.trim().toLowerCase() === deskId.trim().toLowerCase();
}

export function deskContainsContentItem(version: ContentItemVersionRecord, deskId: string): boolean {
  return matchesDesk(version.section, deskId);
}

export function deskContainsAssignment(assignment: AssignmentRecord, deskId: string): boolean {
  return matchesDesk(assignment.sectionId, deskId) || matchesDesk(assignment.sectionKey, deskId);
}

/** A desk board shows stories and assignments side by side; each keeps its own columns and the type filter narrows to one. */
export function deskBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  const storiesConfig = contentItemBoardConfig(issues.filter(issue => issue.kind === "contentItem"));
  const assignmentsConfig = assignmentBoardConfig(issues.filter(issue => issue.kind === "assignment"));
  return {
    ...storiesConfig,
    types: [...(storiesConfig.types ?? []), ...(assignmentsConfig.types ?? [])],
    statuses: [...storiesConfig.statuses, ...assignmentsConfig.statuses],
    categories: storiesConfig.categories,
    workflows: { ...storiesConfig.workflows, ...assignmentsConfig.workflows },
  };
}

export function canReadNewsroomBoard(phase: string | undefined): boolean {
  return phase === "ready";
}
