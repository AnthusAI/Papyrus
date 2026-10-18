import type { KanbanConfig, KanbanIssue } from "@kanbus/ui";
import type { AssignmentRecord } from "./category-repository";
import {
  contentItemStageKeys,
  contentItemStageLabel,
  latestVersionPerContentItem,
  type ContentItemVersionRecord,
} from "./content-item-lifecycle";
import { assignmentStatusLabel } from "./newsroom-assignments";
import { getContentItemName, getContentItemStageDefinitions } from "./site-brand";

export type NativeBoardKind = "contentItem" | "assignment";
export interface NativeBoardIssue extends KanbanIssue {
  kind: NativeBoardKind;
  nativeId: string;
  nativeStatus: string;
  href: string;
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
  return latestVersionPerContentItem(records.contentItemVersions).map(version => {
    const stage = version.stage ?? "idea";
    const workCount = assignmentCountByContentItem.get(version.lineageId) ?? 0;
    return {
      id: `contentItem:${version.lineageId}`, nativeId: version.lineageId, kind: "contentItem" as const, type: contentItemType,
      title: version.headline || version.title || version.slug, nativeStatus: stage, status: `${contentItemType}/${stage}`,
      priority: 2, description: workCount ? `${workCount} assignment${workCount === 1 ? "" : "s"} on this ${contentItemType}.` : undefined,
      updated_at: version.updatedAt ?? undefined, href: `/newsroom/articles/${encodeURIComponent(version.id)}`,
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
    href: `/newsroom/assignments/${encodeURIComponent(row.id)}`,
  }));
}

export function contentItemColumnOrder(
  stagesPresentOnBoard: readonly string[],
  stageKeys: readonly string[] = contentItemStageKeys(getContentItemStageDefinitions()),
): string[] {
  const lastStage = stageKeys[stageKeys.length - 1];
  const unrecognizedStages = [...new Set(stagesPresentOnBoard)].filter(stage => !stageKeys.includes(stage));
  return [...stageKeys.filter(stage => stage !== lastStage), ...unrecognizedStages, lastStage];
}

export function assignmentColumnOrder(statusesPresentOnBoard: readonly string[]): string[] {
  const knownStatuses = [...ASSIGNMENT_STATUSES_BEFORE_OTHERS, ...ASSIGNMENT_STATUSES_AFTER_OTHERS];
  const otherStatuses = [...new Set(statusesPresentOnBoard)].filter(status => !knownStatuses.includes(status));
  return [...ASSIGNMENT_STATUSES_BEFORE_OTHERS, ...otherStatuses, ...ASSIGNMENT_STATUSES_AFTER_OTHERS];
}

function boardConfigForType(type: string, columns: readonly { key: string; name: string }[]): KanbanConfig {
  const statuses = columns.map(column => ({ ...column, category: "native" }));
  return {
    hierarchy: [], types: [type], statuses,
    categories: [{ name: "native" }], priorities: {}, type_colors: {},
    workflows: { [type]: Object.fromEntries(statuses.map(status => [status.key, []])) },
  };
}

/** Content items read left to right through the lifecycle with the final stage last. */
export function contentItemBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  const contentItemType = contentItemBoardType();
  return boardConfigForType(contentItemType, contentItemColumnOrder(issues.map(issue => issue.nativeStatus))
    .map(stage => ({ key: `${contentItemType}/${stage}`, name: contentItemStageLabel(stage, getContentItemStageDefinitions()) })));
}

export function assignmentBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  return boardConfigForType(ASSIGNMENT_BOARD_TYPE, assignmentColumnOrder(issues.map(issue => issue.nativeStatus))
    .map(status => ({ key: `${ASSIGNMENT_BOARD_TYPE}/${status}`, name: assignmentStatusLabel(status) })));
}

export function canReadNewsroomBoard(phase: string | undefined): boolean {
  return phase === "ready";
}
