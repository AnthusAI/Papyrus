import type { HydratedModelPayload, MessageRecord, SemanticRelationRecord } from "./category-repository";
import { normalizeReferenceRejectionReasonCode, type ReferenceRejectionReasonCode } from "./reference-policy";

function metadataRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try { return metadataRecord(JSON.parse(value)); } catch { return {}; }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** The selected Reference's index is authoritative even when the global feed is truncated. */
export async function loadReferenceReviewDetails(lineageId: string, read: {
  relations: (direction: "incoming" | "outgoing") => Promise<SemanticRelationRecord[]>;
  message: (id: string) => Promise<MessageRecord | null>;
  payloads: (id: string) => Promise<HydratedModelPayload[]>;
}): Promise<{ relations: SemanticRelationRecord[]; messages: MessageRecord[] }> {
  const [outgoing, incoming] = await Promise.all([read.relations("outgoing"), read.relations("incoming")]);
  const relations = outgoing.filter((relation) => relation.subjectKind === "reference" && relation.subjectLineageId === lineageId);
  const latest = incoming.filter((relation) => relation.predicate === "comment" && relation.relationState === "current"
    && relation.subjectKind === "message" && relation.objectKind === "reference" && relation.objectLineageId === lineageId
    && metadataRecord(relation.metadata).messageKind === "reference_curation")
    .sort((a, b) => String(b.createdAt ?? b.importedAt ?? "").localeCompare(String(a.createdAt ?? a.importedAt ?? "")))[0];
  if (!latest) return { relations, messages: [] };
  const message = await read.message(latest.subjectId);
  if (!message || message.messageKind !== "reference_curation") throw new Error("The latest reference review could not be loaded.");
  const payload = (await read.payloads(message.id))
    .filter((entry) => entry.attachment.role === "metadata" && entry.attachment.ownerKind === "message" && entry.attachment.ownerId === message.id)
    .sort((a, b) => String(b.attachment.updatedAt ?? "").localeCompare(String(a.attachment.updatedAt ?? "")))[0];
  if (!payload) throw new Error("The latest reference review metadata could not be loaded.");
  if (payload.error) throw new Error(payload.error);
  if (!payload.json || typeof payload.json !== "object" || Array.isArray(payload.json)) {
    throw new Error("The latest reference review metadata is invalid.");
  }
  const hydrated = { ...message, metadata: payload.json };
  const recordedLineage = metadataRecord(hydrated.metadata).referenceLineageId;
  if (recordedLineage !== lineageId) throw new Error("The latest review metadata does not match this reference lineage.");
  return { relations, messages: [hydrated] };
}

function latestReferenceReviews(messages: MessageRecord[]): Map<string, MessageRecord> {
  const latest = new Map<string, MessageRecord>();
  for (const message of messages) {
    if (message.messageKind !== "reference_curation") continue;
    const lineage = metadataRecord(message.metadata).referenceLineageId;
    if (typeof lineage !== "string" || !lineage) continue;
    if (!latest.has(lineage) || String(message.createdAt).localeCompare(String(latest.get(lineage)!.createdAt)) > 0) latest.set(lineage, message);
  }
  return latest;
}

/** A later acceptance or archive clears any earlier rejection reason. */
export function latestReferenceReviewReasons(messages: MessageRecord[]): Map<string, ReferenceRejectionReasonCode> {
  const reasons = new Map<string, ReferenceRejectionReasonCode>();
  for (const [lineage, message] of latestReferenceReviews(messages)) {
    const metadata = metadataRecord(message.metadata);
    const reason = metadata.action === "reject" ? normalizeReferenceRejectionReasonCode(metadata.reasonCode) : null;
    if (reason) reasons.set(lineage, reason);
  }
  return reasons;
}

/** Preserve only a Section explicitly recorded on the newest acceptance, never a prediction. */
export function latestReferenceReviewSections(messages: MessageRecord[]): Map<string, string> {
  const sections = new Map<string, string>();
  for (const [lineage, message] of latestReferenceReviews(messages)) {
    const metadata = metadataRecord(message.metadata);
    const sectionId = metadata.action === "accept" && typeof metadata.sectionId === "string" ? metadata.sectionId.trim() : "";
    if (sectionId) sections.set(lineage, sectionId);
  }
  return sections;
}
