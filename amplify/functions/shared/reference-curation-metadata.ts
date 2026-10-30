/**
 * The details of a vote, kept on the Reference itself (Messages come only from people).
 * When the relevance cyclotron decided the reference, the vote records which decision
 * it answered and whether its explanation may be shared (for the Cyclotron marketing
 * recording). Both are optional. A Reference keeps only its latest vote.
 */
export type ReferenceVoteInput = {
  actorKind: CurationActorKind
  reasonCode?: string | null
  sectionId?: string | null
  decisionRelationId?: string | null
  shareable?: boolean | null
  delegation?: { delegationId: string; relayedBy: string; instruction: string } | null
}

export type CurationActorKind = "human" | "agent" | "cyclotron" | "rule" | "catalog"

/**
 * A curation is human only when the caller signed in through the user pool, so
 * AppSync supplied a verified subject claim. Request arguments never decide it;
 * IAM-signed service callers and agents have no such claim.
 */
export function curationActorKind(identity: unknown): CurationActorKind {
  const claims = (identity as {claims?: Record<string, unknown>} | null | undefined)?.claims
  const subject = claims?.sub
  return typeof subject === "string" && subject.trim() !== "" ? "human" : "agent"
}

/**
 * The Reference fields a vote sets. Every field is always present, so a new vote clears
 * what the last one carried. The delegation is stored as JSON.
 */
export function referenceVoteFields(input: ReferenceVoteInput): Record<string, unknown> {
  const decisionRelationId = input.decisionRelationId?.trim() || null
  return {
    curationActorKind: input.actorKind,
    curationReasonCode: input.reasonCode?.trim() || null,
    curationSectionId: input.sectionId?.trim() || null,
    curationShareable: decisionRelationId ? input.shareable === true : null,
    curationDelegation: input.delegation ? JSON.stringify(input.delegation) : null,
    curationDecisionRelationId: decisionRelationId,
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
