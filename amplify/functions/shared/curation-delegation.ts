import { createHash, randomBytes, randomInt } from "node:crypto"

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
  userCode?: string | null
  requestedHours?: number | null
  pendingExpiresAt?: string | null
  approvedAt?: string | null
  deniedAt?: string | null
}

export type DelegationState = "pending" | "approved" | "denied" | "expired" | "revoked"

export type DelegationVerdict =
  | { ok: true }
  | { ok: false; reason: "unknown-token" | "wrong-agent" | "revoked" | "not-approved" | "expired" }

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
  const state = delegationState(delegation, presented.now)
  if (state === "pending" || state === "denied" || (state === "expired" && delegation.userCode && !delegation.approvedAt)) {
    return { ok: false, reason: "not-approved" }
  }
  if (Date.parse(delegation.expiresAt) <= Date.parse(presented.now)) return { ok: false, reason: "expired" }
  return { ok: true }
}

export function delegationRefusalMessage(reason: Exclude<DelegationVerdict, { ok: true }>["reason"]): string {
  return {
    "unknown-token": "That delegation token is not recognized.",
    "wrong-agent": "That delegation was granted to a different agent.",
    "revoked": "That delegation was revoked.",
    "not-approved": "That delegation has not been approved by a person. Ask them to approve the code in the Newsroom.",
    "expired": "That delegation has expired. Ask the person for a new one.",
  }[reason]
}

export const PENDING_DELEGATION_MINUTES = 10
export const MAXIMUM_PENDING_DELEGATION_REQUESTS = 5
export const PENDING_REQUEST_GRANTOR_SUB = "pending-device-authorization"
export const EXPIRED_REQUEST_GRANTOR_SUB = "expired-device-authorization"
export const USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
export const USER_CODE_LENGTH = 8

export function newUserCode(): string {
  let code = ""
  for (let position = 0; position < USER_CODE_LENGTH; position += 1) {
    code += USER_CODE_ALPHABET[randomInt(USER_CODE_ALPHABET.length)]
  }
  return code
}

export function formatUserCode(code: string): string {
  return `${code.slice(0, 4)}-${code.slice(4)}`
}

export function normalizeUserCode(typed: string | null | undefined): string | null {
  const stripped = (typed ?? "").toUpperCase().replace(/[\s-]/g, "")
  if (stripped.length !== USER_CODE_LENGTH) return null
  for (const character of stripped) if (!USER_CODE_ALPHABET.includes(character)) return null
  return stripped
}

export function delegationState(delegation: CurationDelegation, now: string): DelegationState {
  if (delegation.revokedAt) return "revoked"
  if (delegation.deniedAt) return "denied"
  if (delegation.userCode && !delegation.approvedAt) {
    const pendingEnd = delegation.pendingExpiresAt ?? delegation.expiresAt
    return Date.parse(pendingEnd) <= Date.parse(now) ? "expired" : "pending"
  }
  return Date.parse(delegation.expiresAt) <= Date.parse(now) ? "expired" : "approved"
}
