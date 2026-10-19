/**
 * Metadata stored with an editor's reference curation Message. When the
 * relevance cyclotron decided the reference, the review records which
 * decision it answered and whether its explanation may be shared (for the
 * Cyclotron marketing recording). Both are optional.
 */
export type ReferenceCurationMetadataInput = {
  action: string
  curationStatus: string
  reasonCode: string | null
  referenceId: string
  referenceLineageId: string
  decisionRelationId?: string | null
  shareable?: boolean | null
  actorKind?: CurationActorKind | null
  sectionId?: string | null
  delegation?: { delegationId: string; relayedBy: string; instruction: string } | null
}

export type CurationActorKind = "human" | "service"

/**
 * A curation is human only when the caller signed in through the user pool, so
 * AppSync supplied a verified subject claim. Request arguments never decide it;
 * IAM-signed service callers and agents have no such claim.
 */
export function curationActorKind(identity: unknown): CurationActorKind {
  const claims = (identity as {claims?: Record<string, unknown>} | null | undefined)?.claims
  const subject = claims?.sub
  return typeof subject === "string" && subject.trim() !== "" ? "human" : "service"
}

export function referenceCurationMetadata(input: ReferenceCurationMetadataInput): Record<string, unknown> {
  const decisionRelationId = input.decisionRelationId?.trim() || null
  return {
    action: input.action,
    curationStatus: input.curationStatus,
    reasonCode: input.reasonCode,
    curationReasonCode: input.reasonCode,
    referenceId: input.referenceId,
    referenceLineageId: input.referenceLineageId,
    ...(input.actorKind ? {actorKind: input.actorKind} : {}),
    ...(input.sectionId?.trim() ? {sectionId: input.sectionId.trim()} : {}),
    ...(input.delegation
      ? {attestation: "delegated", relayedBy: input.delegation.relayedBy, delegationId: input.delegation.delegationId,
         instruction: input.delegation.instruction}
      : {}),
    ...(decisionRelationId ? {decisionRelationId} : {}),
    ...(decisionRelationId ? {shareable: input.shareable === true} : {}),
  }
}

export type CurationSectionCandidate = {
  id?: string | null
  enabled?: boolean | null
  enabledStatus?: string | null
} | null | undefined

/**
 * A curation may name the newsroom Section the Reference belongs in, but only
 * when it accepts the Reference and the Section exists and is enabled.
 */
export function validatedCurationSectionId(
  requestedSectionId: string | null | undefined,
  action: string,
  section: CurationSectionCandidate,
): string | null {
  const sectionId = requestedSectionId?.trim() || null
  if (!sectionId) return null
  if (action !== "accept") {
    throw new Error("A section can be recorded only when accepting a reference.")
  }
  if (!section || section.id !== sectionId) {
    throw new Error(`Newsroom section ${sectionId} was not found.`)
  }
  if (section.enabled === false || section.enabledStatus === "disabled") {
    throw new Error(`Newsroom section ${sectionId} is disabled.`)
  }
  return sectionId
}
