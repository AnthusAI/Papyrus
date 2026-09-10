import type { AssignmentRecord, NewsroomSummaryRecord } from "./category-repository";

export type AssignmentStatusFilter = "all" | "open" | "claimed" | "completed" | "canceled";

export type AssignmentAction = "claim" | "release" | "complete" | "cancel" | "reopen" | "retry";

export type AssignmentTypeOption = {
  key: string;
  label: string;
  count: number;
};

export type AssignmentMetrics = {
  total: number;
  open: number;
  claimed: number;
  completed: number;
  canceled: number;
};

export function assignmentTypeKeyForFilter(assignment: AssignmentRecord): string {
  return assignment.assignmentTypeKey?.trim() || "unknown";
}

export function formatAssignmentTypeLabel(typeKey: string | null | undefined): string {
  const key = typeKey?.trim();
  if (!key) return "Uncategorized";
  if (key === "analysis.reindex") return "Analysis re-index";
  if (key === "newsroom.research" || key === "research") return "Research";
  if (key === "curation.reference-intake") return "Reference intake";
  if (key === "reporting.edition-candidate") return "Reporting candidate";
  return key
    .split(/[.:_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function getAssignmentTypeOptions(
  assignments: AssignmentRecord[],
  summary?: NewsroomSummaryRecord | null,
): AssignmentTypeOption[] {
  const summaryCounts = summary?.facets?.assignments?.byType ?? summary?.assignmentTypeCounts;
  const countByType = summaryCounts && Object.keys(summaryCounts).length
    ? new Map(Object.entries(summaryCounts))
    : new Map<string, number>();
  if (!countByType.size) {
    for (const assignment of assignments) {
      const typeKey = assignmentTypeKeyForFilter(assignment);
      countByType.set(typeKey, (countByType.get(typeKey) ?? 0) + 1);
    }
  }
  return Array.from(countByType.entries())
    .map(([key, count]) => ({
      key,
      label: formatAssignmentTypeLabel(key),
      count,
    }))
    .sort((left, right) => {
      const countDiff = right.count - left.count;
      if (countDiff !== 0) return countDiff;
      return left.label.localeCompare(right.label);
    });
}

export function getAssignmentMetrics(
  assignments: AssignmentRecord[],
  summary?: NewsroomSummaryRecord | null,
  typeFilter?: string,
): AssignmentMetrics {
  const statusCounts = typeFilter
    ? summary?.facets?.assignments?.statusByType?.[typeFilter]
    : summary?.facets?.assignments?.byStatus ?? summary?.assignmentStatusCounts;
  if (statusCounts && Object.keys(statusCounts).length) {
    return {
      total: Object.values(statusCounts).reduce((sum, count) => sum + count, 0),
      open: statusCounts.open ?? 0,
      claimed: statusCounts.claimed ?? 0,
      completed: statusCounts.completed ?? 0,
      canceled: statusCounts.canceled ?? 0,
    };
  }
  return {
    total: assignments.length,
    open: assignments.filter((assignment) => assignment.status === "open").length,
    claimed: assignments.filter((assignment) => assignment.status === "claimed").length,
    completed: assignments.filter((assignment) => assignment.status === "completed").length,
    canceled: assignments.filter((assignment) => assignment.status === "canceled").length,
  };
}

function assignmentStatusRank(status: string): number {
  if (status === "open") return 0;
  if (status === "claimed") return 1;
  if (status === "completed") return 6;
  if (status === "canceled") return 8;
  return 5;
}

export function compareAssignments(left: AssignmentRecord, right: AssignmentRecord): number {
  const leftStatus = assignmentStatusRank(left.status);
  const rightStatus = assignmentStatusRank(right.status);
  if (leftStatus !== rightStatus) return leftStatus - rightStatus;
  const priorityDiff = (left.priority ?? 999999) - (right.priority ?? 999999);
  if (priorityDiff !== 0) return priorityDiff;
  return left.createdAt.localeCompare(right.createdAt);
}

export function countAssignmentsByStatus(assignments: AssignmentRecord[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const assignment of assignments) {
    const status = assignment.status?.trim().toLowerCase() || "unknown";
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

export function filterAssignmentsByStatus(
  assignments: AssignmentRecord[],
  statusFilter: AssignmentStatusFilter,
): AssignmentRecord[] {
  const sorted = [...assignments].sort(compareAssignments);
  if (statusFilter === "all") return sorted;
  return sorted.filter((assignment) => assignment.status === statusFilter);
}

export function formatAssignmentListDate(assignment: AssignmentRecord): string {
  const value = assignment.updatedAt ?? assignment.createdAt ?? "";
  if (!value) return "Undated";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(timestamp));
}

export function assignmentStatusLabel(status: string): string {
  const normalized = status?.trim().toLowerCase() ?? "";
  if (normalized === "open") return "Open";
  if (normalized === "claimed") return "Claimed";
  if (normalized === "completed") return "Completed";
  if (normalized === "canceled") return "Canceled";
  return status || "Unknown";
}

export function assignmentStatusBadgeVariant(
  status: string,
): "default" | "secondary" | "outline" | "muted" {
  const normalized = status?.trim().toLowerCase() ?? "";
  if (normalized === "open") return "default";
  if (normalized === "claimed") return "secondary";
  if (normalized === "completed") return "outline";
  if (normalized === "canceled") return "outline";
  return "muted";
}

export function assignmentListSubtitle(assignment: AssignmentRecord): string {
  const typeLabel = formatAssignmentTypeLabel(assignment.assignmentTypeKey);
  const section = assignment.sectionKey?.trim() || assignment.sectionId?.trim();
  if (section) return `${typeLabel} · ${section}`;
  return typeLabel;
}

export function selectedAssignmentById(
  assignments: AssignmentRecord[],
  assignmentId: string | null | undefined,
): AssignmentRecord | null {
  if (!assignmentId) return null;
  return assignments.find((assignment) => assignment.id === assignmentId) ?? null;
}
