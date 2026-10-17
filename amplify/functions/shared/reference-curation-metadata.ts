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
    ...(decisionRelationId ? {decisionRelationId} : {}),
    ...(decisionRelationId ? {shareable: input.shareable === true} : {}),
  }
}
