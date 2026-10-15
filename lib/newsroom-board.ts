import type { KanbanConfig, KanbanIssue } from "@kanbus/ui";
import type { AssignmentRecord, ReferenceRecord } from "./category-repository";
import type { NewsroomArticleRow } from "./newsroom-articles";

export type NativeBoardKind = "article" | "reference" | "assignment";
export interface NativeBoardIssue extends KanbanIssue {
  type: NativeBoardKind;
  nativeId: string;
  nativeStatus: string;
  href: string;
}

/** Native records keep their own identity, status and mutation authority. No Story linkage is inferred. */
export function projectNewsroomBoard(records: {
  articles?: readonly NewsroomArticleRow[];
  references?: readonly ReferenceRecord[];
  assignments?: readonly AssignmentRecord[];
}): NativeBoardIssue[] {
  return [
    ...(records.articles ?? []).map(row => ({
      id: `article:${row.id}`, nativeId: row.id, type: "article" as const,
      title: row.title, nativeStatus: row.status, status: `article/${row.status}`,
      priority: 2, description: row.pending ? "Published copy has pending draft changes." : undefined,
      updated_at: row.updatedAt, href: `/newsroom/articles/${encodeURIComponent(row.id)}`,
    })),
    ...(records.references ?? []).filter(row => !row.versionState || row.versionState === "current").map(row => ({
      id: `reference:${row.id}`, nativeId: row.id, type: "reference" as const,
      title: row.title || row.externalItemId || row.id,
      nativeStatus: row.curationStatus || "pending", status: `reference/${row.curationStatus || "pending"}`,
      priority: 2, description: row.curationStatusReason || undefined,
      updated_at: row.updatedAt || row.importedAt || undefined,
      href: `/newsroom/references/${encodeURIComponent(row.lineageId || row.id)}`,
    })),
    ...(records.assignments ?? []).map(row => ({
      id: `assignment:${row.id}`, nativeId: row.id, type: "assignment" as const,
      title: row.title, nativeStatus: row.status, status: `assignment/${row.status}`,
      priority: row.priority ?? 2, assignee: row.assigneeId || undefined,
      description: row.summary || row.brief || undefined,
      created_at: row.createdAt, updated_at: row.updatedAt,
      href: `/newsroom/assignments/${encodeURIComponent(row.id)}`,
    })),
  ];
}

/** Unknown native statuses remain visible instead of being translated into invented stages. */
export function newsroomBoardConfig(issues: readonly NativeBoardIssue[]): KanbanConfig {
  const keys = [...new Set(issues.map(issue => issue.status))];
  return {
    hierarchy: [], types: ["article", "reference", "assignment"],
    statuses: keys.map(key => ({ key, name: key.replace("/", " · "), category: "native" })),
    categories: [{ name: "native" }], priorities: {}, type_colors: {},
    workflows: Object.fromEntries(["article", "reference", "assignment"].map(kind => [kind,
      Object.fromEntries(keys.filter(key => key.startsWith(`${kind}/`)).map(key => [key, []])),
    ])),
  };
}

export function canReadNewsroomBoard(phase: string | undefined): boolean {
  return phase === "ready";
}
