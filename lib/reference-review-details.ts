import type { ReferenceRecord, SemanticRelationRecord } from "./category-repository";
import { normalizeReferenceRejectionReasonCode, type ReferenceRejectionReasonCode } from "./reference-policy";

/**
 * The selected Reference's indexed predictions (the Cyclotron's relevance decisions). The Reference's own latest vote
 * (`curationActorKind`, `curationReasonCode`, ...) is already on the Reference, so no Message is read.
 */
export async function loadReferenceReviewDetails(lineageId: string, read: {
  relations: (direction: "outgoing") => Promise<SemanticRelationRecord[]>;
}): Promise<{ relations: SemanticRelationRecord[] }> {
  const outgoing = await read.relations("outgoing");
  return { relations: outgoing.filter((relation) => relation.subjectKind === "reference" && relation.subjectLineageId === lineageId) };
}

/** The reason code of each rejected Reference's latest vote. A later acceptance or archive replaced the vote, so it clears the reason. */
export function latestReferenceReviewReasons(references: readonly ReferenceRecord[]): Map<string, ReferenceRejectionReasonCode> {
  const reasons = new Map<string, ReferenceRejectionReasonCode>();
  for (const reference of references) {
    if (!reference.curationActorKind || reference.curationStatus !== "rejected") continue;
    const reason = normalizeReferenceRejectionReasonCode(reference.curationReasonCode);
    if (reason) reasons.set(reference.lineageId ?? reference.id, reason);
  }
  return reasons;
}

/** The Section a person explicitly recorded on a Reference's latest vote when accepting it, never a prediction. */
export function latestReferenceReviewSections(references: readonly ReferenceRecord[]): Map<string, string> {
  const sections = new Map<string, string>();
  for (const reference of references) {
    if (!reference.curationActorKind || reference.curationStatus !== "accepted") continue;
    const sectionId = reference.curationSectionId?.trim() ?? "";
    if (sectionId) sections.set(reference.lineageId ?? reference.id, sectionId);
  }
  return sections;
}
