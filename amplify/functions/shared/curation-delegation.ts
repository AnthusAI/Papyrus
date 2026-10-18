import { createHash, randomBytes } from "node:crypto"

export const CURATION_DELEGATION_PAYLOAD_KIND = "curation-delegation"
export const CURATION_DELEGATION_OWNER_TYPE = "curationDelegation"
export const DEFAULT_DELEGATION_HOURS = 8
export const MAXIMUM_DELEGATION_HOURS = 72

export type CurationDelegation = {
  delegationId: string
  tokenHash: string
  grantorSub: string
  grantorLabel: string
  agentLabel: string
  createdAt: string
  expiresAt: string
  revokedAt: string | null
}

export type DelegationVerdict =
  | { ok: true }
  | { ok: false; reason: "unknown-token" | "wrong-agent" | "revoked" | "expired" }

export function hashDelegationToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex")
}

export function newDelegationToken(delegationId: string): { token: string; tokenHash: string } {
  const token = `${delegationId}~${randomBytes(24).toString("base64url")}`
  return { token, tokenHash: hashDelegationToken(token) }
}

export function delegationIdFromToken(token: string): string | null {
  const separator = token.indexOf("~")
  return separator > 0 ? token.slice(0, separator) : null
}

export function delegationExpiry(now: string, hours: number | null | undefined): string {
  const requested = hours ?? DEFAULT_DELEGATION_HOURS
  if (!Number.isFinite(requested) || requested <= 0 || requested > MAXIMUM_DELEGATION_HOURS) {
    throw new Error(`A delegation lasts between 1 and ${MAXIMUM_DELEGATION_HOURS} hours.`)
  }
  return new Date(Date.parse(now) + requested * 3_600_000).toISOString()
}

export function delegationVerdict(
  delegation: CurationDelegation | null,
  presented: { token: string; agentLabel: string; now: string },
): DelegationVerdict {
  if (!delegation || delegation.tokenHash !== hashDelegationToken(presented.token)) {
    return { ok: false, reason: "unknown-token" }
  }
  if (delegation.agentLabel.trim().toLowerCase() !== presented.agentLabel.trim().toLowerCase()) {
    return { ok: false, reason: "wrong-agent" }
  }
  if (delegation.revokedAt) return { ok: false, reason: "revoked" }
  if (Date.parse(delegation.expiresAt) <= Date.parse(presented.now)) return { ok: false, reason: "expired" }
  return { ok: true }
}

export function delegationRefusalMessage(reason: Exclude<DelegationVerdict, { ok: true }>["reason"]): string {
  return {
    "unknown-token": "That delegation token is not recognized.",
    "wrong-agent": "That delegation was granted to a different agent.",
    "revoked": "That delegation was revoked.",
    "expired": "That delegation has expired. Ask the person for a new one.",
  }[reason]
}
