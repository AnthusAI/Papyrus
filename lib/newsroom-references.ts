import type { ReferenceRecord } from "./category-repository";
import { normalizeReferenceCurationStatus } from "./reference-policy";

export type ReferenceCurationAction = "accept" | "reject" | "archive";

export type ReferenceStatusFilter = "all" | "pending" | "accepted" | "rejected" | "archived";

export function referenceLineageId(reference: ReferenceRecord): string {
  return reference.lineageId ?? reference.id;
}

export function normalizeReferenceStatus(status: string | null | undefined): string {
  return normalizeReferenceCurationStatus(status);
}

function referenceSortDate(reference: ReferenceRecord): string {
  return reference.sourcePublishedAt
    ?? reference.sourceUpdatedAt
    ?? reference.retrievedAt
    ?? reference.importedAt
    ?? reference.updatedAt
    ?? "";
}

export function compareReferencesByRecency(left: ReferenceRecord, right: ReferenceRecord): number {
  const dateDiff = referenceSortDate(right).localeCompare(referenceSortDate(left));
  if (dateDiff !== 0) return dateDiff;
  return (left.title ?? left.externalItemId).localeCompare(right.title ?? right.externalItemId);
}

function compareReferencesForCanonicalChoice(left: ReferenceRecord, right: ReferenceRecord): number {
  const leftCurrent = left.versionState === "current" ? 1 : 0;
  const rightCurrent = right.versionState === "current" ? 1 : 0;
  if (leftCurrent !== rightCurrent) return rightCurrent - leftCurrent;

  const leftVersion = Number.isFinite(left.versionNumber) ? Number(left.versionNumber) : 0;
  const rightVersion = Number.isFinite(right.versionNumber) ? Number(right.versionNumber) : 0;
  if (leftVersion !== rightVersion) return rightVersion - leftVersion;

  return compareReferencesByRecency(left, right);
}

export function selectCanonicalReferenceRecords(references: ReferenceRecord[]): ReferenceRecord[] {
  const byLineage = new Map<string, ReferenceRecord>();
  for (const reference of references) {
    const key = referenceLineageId(reference);
    const current = byLineage.get(key);
    if (!current || compareReferencesForCanonicalChoice(reference, current) < 0) {
      byLineage.set(key, reference);
    }
  }
  return Array.from(byLineage.values()).sort(compareReferencesByRecency);
}

export function selectedReferenceRecordByLineage(
  references: ReferenceRecord[],
  requestedLineageId: string | null | undefined,
): ReferenceRecord | null {
  if (!requestedLineageId) return null;
  const lineageMatches = references.filter((reference) => referenceLineageId(reference) === requestedLineageId);
  if (!lineageMatches.length) return null;
  return lineageMatches.reduce((best, current) => (
    compareReferencesForCanonicalChoice(current, best) < 0 ? current : best
  ));
}

export function countReferencesByStatus(references: ReferenceRecord[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const reference of references) {
    const status = normalizeReferenceStatus(reference.curationStatus);
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

export function filterReferencesByStatus(
  references: ReferenceRecord[],
  statusFilter: ReferenceStatusFilter,
): ReferenceRecord[] {
  const canonical = selectCanonicalReferenceRecords(references);
  if (statusFilter === "all") return canonical;
  return canonical.filter((reference) => normalizeReferenceStatus(reference.curationStatus) === statusFilter);
}

export function formatReferenceListDate(reference: ReferenceRecord): string {
  const value = referenceSortDate(reference);
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

export function referenceDisplayTitle(reference: ReferenceRecord): string {
  return reference.title?.trim() || reference.externalItemId;
}

export function referenceStatusLabel(status: string): string {
  if (status === "accepted") return "Accepted";
  if (status === "rejected") return "Rejected";
  if (status === "archived") return "Archived";
  return "Pending";
}

export function referenceStatusBadgeVariant(
  status: string,
): "default" | "secondary" | "outline" | "muted" {
  if (status === "accepted") return "default";
  if (status === "rejected") return "outline";
  if (status === "archived") return "secondary";
  return "muted";
}
