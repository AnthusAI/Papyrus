import type { MessageRecord, ReferenceRecord } from "./category-repository";

export const REFERENCE_CURATION_STATUSES = ["pending", "accepted", "rejected", "archived"] as const;
export type ReferenceCurationStatus = typeof REFERENCE_CURATION_STATUSES[number];

export const REFERENCE_REJECTION_REASON_CODES = [
  "out_of_scope",
  "policy_exclusion",
  "duplicate",
  "low_quality",
  "unavailable",
  "provenance",
  "other",
] as const;
export type ReferenceRejectionReasonCode = typeof REFERENCE_REJECTION_REASON_CODES[number];

const REFERENCE_REJECTION_REASON_CODE_SET = new Set<string>(REFERENCE_REJECTION_REASON_CODES);
const SCOPE_TRAINING_NEGATIVE_REASON_CODE_SET = new Set<string>(["out_of_scope", "policy_exclusion"]);

/** Rejection reasons that say the source is not relevant (scope-training negatives). */
export function isScopeTrainingNegativeReason(code: string): boolean {
  return SCOPE_TRAINING_NEGATIVE_REASON_CODE_SET.has(code);
}

export function normalizeReferenceCurationStatus(value: unknown, defaultStatus: ReferenceCurationStatus = "pending"): ReferenceCurationStatus {
  const normalized = normalizePolicyToken(value ?? defaultStatus);
  if (normalized === "accepted" || normalized === "accept" || normalized === "ready" || normalized === "trusted") return "accepted";
  if (normalized === "rejected" || normalized === "reject" || normalized === "discarded") return "rejected";
  if (normalized === "archived" || normalized === "archive") return "archived";
  return "pending";
}

export function referenceCurationStatusForAction(action: "accept" | "reject" | "reopen" | "archive"): ReferenceCurationStatus {
  if (action === "accept") return "accepted";
  if (action === "reject") return "rejected";
  if (action === "archive") return "archived";
  return "pending";
}

export function normalizeReferenceRejectionReasonCode(value: unknown): ReferenceRejectionReasonCode | null {
  const normalized = normalizePolicyToken(value);
  if (!normalized) return null;
  return REFERENCE_REJECTION_REASON_CODE_SET.has(normalized) ? normalized as ReferenceRejectionReasonCode : null;
}

export function isEvidenceEligibleReference(reference: Pick<ReferenceRecord, "versionState" | "curationStatus"> | null | undefined): boolean {
  return Boolean(reference)
    && reference?.versionState === "current"
    && normalizeReferenceCurationStatus(reference?.curationStatus) === "accepted";
}

export function referenceReasonCode(reference: Pick<ReferenceRecord, "metadata"> | null | undefined, messages: Array<Pick<MessageRecord, "metadata" | "createdAt">> = []): ReferenceRejectionReasonCode | null {
  const metadataReason = reasonCodeFromMetadata(reference?.metadata);
  if (metadataReason) return metadataReason;
  const sortedMessages = [...messages].sort((left, right) => String(right.createdAt ?? "").localeCompare(String(left.createdAt ?? "")));
  for (const message of sortedMessages) {
    const reason = reasonCodeFromMetadata(message.metadata);
    if (reason) return reason;
  }
  return null;
}

export function scopeTrainingLabelForReference(reference: Pick<ReferenceRecord, "versionState" | "curationStatus" | "metadata"> | null | undefined, messages: Array<Pick<MessageRecord, "metadata" | "createdAt">> = []): "positive" | "negative" | null {
  if (!reference || reference.versionState !== "current") return null;
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  if (status === "accepted") return "positive";
  if (status !== "rejected") return null;
  const reasonCode = referenceReasonCode(reference, messages);
  return reasonCode && SCOPE_TRAINING_NEGATIVE_REASON_CODE_SET.has(reasonCode) ? "negative" : null;
}

function reasonCodeFromMetadata(metadata: unknown): ReferenceRejectionReasonCode | null {
  const parsed = parseMetadataObject(metadata);
  return normalizeReferenceRejectionReasonCode(
    parsed.reasonCode
      ?? parsed.reason_code
      ?? parsed.curationReasonCode
      ?? parsed.curation_reason_code
      ?? parsed.rejectionReasonCode
      ?? parsed.rejection_reason_code,
  );
}

function parseMetadataObject(value: unknown): Record<string, unknown> {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function normalizePolicyToken(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}
