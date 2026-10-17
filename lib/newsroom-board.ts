import type { KanbanConfig, KanbanIssue } from "@kanbus/ui";
import type { AssignmentRecord, ReferenceRecord } from "./category-repository";
import {
  CONTENT_ITEM_STAGES,
  contentItemStageLabel,
  latestVersionPerContentItem,
  type ContentItemVersionRecord,
} from "./content-item-lifecycle";
import { getContentItemName } from "./site-brand";

export type NativeBoardKind = "contentItem" | "reference" | "assignment";
export interface NativeBoardIssue extends KanbanIssue {
  kind: NativeBoardKind;
  nativeId: string;
  nativeStatus: string;
  href: string;
}

export function contentItemBoardType(): string {
  return getContentItemName().singular.toLowerCase();
}

function boardTypeForKind(kind: NativeBoardKind): string {
  return kind === "contentItem" ? contentItemBoardType() : kind;
}

/**
 * One card per content item, in the column for its lifecycle stage. Assignments that are work on a content item
 * are counted on that item's card rather than shown as separate cards. References and other work keep their own
 * identity and native status.
 */
export function projectNewsroomBoard(records: {
  contentItemVersions?: readonly ContentItemVersionRecord[];
  references?: readonly ReferenceRecord[];
  assignments?: readonly AssignmentRecord[];
}): NativeBoardIssue[] {
  const assignmentCountByContentItem = new Map<string, number>();
  for (const assignment of records.assignments ?? []) {
    if (assignment.itemLineageId) {
      assignmentCountByContentItem.set(assignment.itemLineageId, (assignmentCountByContentItem.get(assignment.itemLineageId) ?? 0) + 1);
    }
  }
  const contentItemType = contentItemBoardType();
  return [
    ...latestVersionPerContentItem(records.contentItemVersions ?? []).map(version => {
      const stage = version.stage ?? "idea";
      const workCount = assignmentCountByContentItem.get(version.lineageId) ?? 0;
      return {
        id: `contentItem:${version.lineageId}`, nativeId: version.lineageId, kind: "contentItem" as const, type: contentItemType,
        title: version.headline || version.title || version.slug, nativeStatus: stage, status: `${contentItemType}/${stage}`,
        priority: 2, description: workCount ? `${workCount} assignment${workCount === 1 ? "" : "s"} on this ${contentItemType}.` : undefined,
        updated_at: version.updatedAt ?? undefined, href: `/newsroom/articles/${encodeURIComponent(version.id)}`,
      };
    }),
    ...(records.references ?? []).filter(row => !row.versionState || row.versionState === "current").map(row => ({
      id: `reference:${row.id}`, nativeId: row.id, kind: "reference" as const, type: "reference",
      title: row.title || row.externalItemId || row.id,
      nativeStatus: row.curationStatus || "pending", status: `reference/${row.curationStatus || "pending"}`,
      priority: 2, description: row.curationStatusReason || undefined,
      updated_at: row.updatedAt || row.importedAt || undefined,
      href: `/newsroom/references/${encodeURIComponent(row.lineageId || row.id)}`,
    })),
    ...(records.assignments ?? []).filter(row => !row.itemLineageId).map(row => ({
      id: `assignment:${row.id}`, nativeId: row.id, kind: "assignment" as const, type: "assignment",
      title: row.title, nativeStatus: row.status, status: `assignment/${row.status}`,
      priority: row.priority ?? 2, assignee: row.assigneeId || undefined,
      description: row.summary || row.brief || undefined,
      created_at: row.createdAt, updated_at: row.updatedAt,
      href: `/newsroom/assignments/${encodeURIComponent(row.id)}`,
    })),
  ];
}

export function contentItemColumnOrder(stagesPresentOnBoard: readonly string[]): string[] {
  const lastStage = CONTENT_ITEM_STAGES[CONTENT_ITEM_STAGES.length - 1];
  const unrecognizedStages = [...new Set(stagesPresentOnBoard)].filter(stage => !(CONTENT_ITEM_STAGES as readonly string[]).includes(stage));
  return [...CONTENT_ITEM_STAGES.filter(stage => stage !== lastStage), ...unrecognizedStages, lastStage];
}

/** Content items read left to right through the lifecycle with the final stage last; other record kinds follow it. */
export function newsroomBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  const contentItemType = contentItemBoardType();
  const kinds: NativeBoardKind[] = ["contentItem", "reference", "assignment"];
  const contentItemStatuses = contentItemColumnOrder(issues.filter(issue => issue.kind === "contentItem").map(issue => issue.nativeStatus))
    .map(stage => ({ key: `${contentItemType}/${stage}`, name: contentItemStageLabel(stage), category: "native" }));
  const otherStatuses = [...new Set(issues.filter(issue => issue.kind !== "contentItem").map(issue => issue.status))]
    .map(key => ({ key, name: key.replace("/", " · "), category: "native" }));
  const statuses = [...contentItemStatuses, ...otherStatuses];
  return {
    hierarchy: [], types: kinds.map(boardTypeForKind),
    statuses,
    categories: [{ name: "native" }], priorities: {}, type_colors: {},
    workflows: Object.fromEntries(kinds.map(kind => {
      const type = boardTypeForKind(kind);
      return [type, Object.fromEntries(statuses.filter(status => status.key.startsWith(`${type}/`)).map(status => [status.key, []]))];
    })),
  };
}

export function canReadNewsroomBoard(phase: string | undefined): boolean {
  return phase === "ready";
}
