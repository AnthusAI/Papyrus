import {
  EXPIRED_REQUEST_GRANTOR_SUB,
  MAXIMUM_PENDING_DELEGATION_REQUESTS,
  PENDING_DELEGATION_MINUTES,
  PENDING_REQUEST_GRANTOR_SUB,
  delegationExpiry,
  delegationState,
  formatUserCode,
  newUserCode,
  normalizeUserCode,
  type CurationDelegation,
} from "./curation-delegation"

export type DelegationStore = {
  read(delegationId: string): Promise<CurationDelegation | null>
  write(delegation: CurationDelegation, now: string, created: boolean): Promise<void>
  listPending(): Promise<CurationDelegation[]>
}

export type SignedInPerson = { sub: string; label: string; isAdmin: boolean }

const DELEGATION_ID_PATTERN = /^curation-delegation-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TOKEN_HASH_PATTERN = /^[0-9a-f]{64}$/
const MAXIMUM_AGENT_LABEL_LENGTH = 80
const USER_CODE_ATTEMPTS = 50

export function delegationResult(delegation: CurationDelegation, now: string) {
  const state = delegationState(delegation, now)
  return {
    ok: true,
    delegationId: delegation.delegationId,
    token: null,
    agentLabel: delegation.agentLabel,
    grantorLabel: delegation.grantorLabel || null,
    expiresAt: delegation.expiresAt,
    revokedAt: delegation.revokedAt,
    state,
    userCode: state === "pending" && delegation.userCode ? formatUserCode(delegation.userCode) : null,
    requestedHours: delegation.requestedHours ?? null,
    pendingExpiresAt: delegation.pendingExpiresAt ?? null,
    approvedAt: delegation.approvedAt ?? null,
    deniedAt: delegation.deniedAt ?? null,
  }
}

export async function livePendingRequests(store: DelegationStore, now: string): Promise<CurationDelegation[]> {
  const live: CurationDelegation[] = []
  for (const candidate of await store.listPending()) {
    if (delegationState(candidate, now) === "pending") {
      live.push(candidate)
    } else if (candidate.grantorSub === PENDING_REQUEST_GRANTOR_SUB) {
      await store.write({ ...candidate, grantorSub: EXPIRED_REQUEST_GRANTOR_SUB }, now, false)
    }
  }
  return live
}

export async function requestDelegation(
  store: DelegationStore,
  input: { delegationId: string; tokenHash: string; agentLabel: string; hours: number | null | undefined },
  now: string,
) {
  if (!DELEGATION_ID_PATTERN.test(input.delegationId)) {
    throw new Error("The delegation id must look like curation-delegation-<uuid>.")
  }
  if (!TOKEN_HASH_PATTERN.test(input.tokenHash)) throw new Error("The token hash must be 64 lowercase hexadecimal characters.")
  const agentLabel = input.agentLabel.trim()
  if (!agentLabel) throw new Error("Name the agent asking for the delegation.")
  if (agentLabel.length > MAXIMUM_AGENT_LABEL_LENGTH) throw new Error("The agent name is too long.")
  const requestedHours = input.hours ?? 8
  delegationExpiry(now, requestedHours)
  if (await store.read(input.delegationId)) throw new Error("That delegation id is already in use.")
  const live = await livePendingRequests(store, now)
  if (live.length >= MAXIMUM_PENDING_DELEGATION_REQUESTS) {
    throw new Error("Too many delegation requests are waiting for approval. Try again later.")
  }
  const takenCodes = new Set(live.map((request) => request.userCode))
  let userCode = newUserCode()
  for (let attempt = 0; takenCodes.has(userCode); attempt += 1) {
    if (attempt >= USER_CODE_ATTEMPTS) throw new Error("Could not allocate a unique approval code. Try again.")
    userCode = newUserCode()
  }
  const pendingExpiresAt = new Date(Date.parse(now) + PENDING_DELEGATION_MINUTES * 60_000).toISOString()
  const delegation: CurationDelegation = {
    delegationId: input.delegationId,
    tokenHash: input.tokenHash,
    grantorSub: PENDING_REQUEST_GRANTOR_SUB,
    grantorLabel: "",
    agentLabel,
    createdAt: now,
    expiresAt: pendingExpiresAt,
    revokedAt: null,
    userCode,
    requestedHours,
    pendingExpiresAt,
    approvedAt: null,
    deniedAt: null,
  }
  await store.write(delegation, now, true)
  return {
    ok: true,
    delegationId: delegation.delegationId,
    userCode: formatUserCode(userCode),
    pendingExpiresAt,
    requestedHours,
  }
}

async function findLivePendingByCode(store: DelegationStore, typedCode: string, now: string): Promise<CurationDelegation> {
  const code = normalizeUserCode(typedCode)
  const found = code ? (await livePendingRequests(store, now)).find((request) => request.userCode === code) : undefined
  if (!found) throw new Error("No pending delegation request has that code. It may have expired or already been decided.")
  return found
}

export async function approveDelegation(store: DelegationStore, person: SignedInPerson, typedCode: string, now: string) {
  const pending = await findLivePendingByCode(store, typedCode, now)
  const approved: CurationDelegation = {
    ...pending,
    grantorSub: person.sub,
    grantorLabel: person.label,
    createdAt: now,
    expiresAt: delegationExpiry(now, pending.requestedHours),
    approvedAt: now,
    userCode: null,
  }
  await store.write(approved, now, false)
  return delegationResult(approved, now)
}

export async function denyDelegation(store: DelegationStore, person: SignedInPerson, typedCode: string, now: string) {
  const pending = await findLivePendingByCode(store, typedCode, now)
  const denied: CurationDelegation = { ...pending, grantorSub: person.sub, grantorLabel: person.label, deniedAt: now, userCode: null }
  await store.write(denied, now, false)
  return delegationResult(denied, now)
}

export async function delegationStatus(store: DelegationStore, delegationId: string, now: string) {
  const delegation = await store.read(delegationId)
  if (!delegation) throw new Error("That delegation was not found.")
  return {
    delegationId: delegation.delegationId,
    state: delegationState(delegation, now),
    expiresAt: delegation.expiresAt,
    grantorLabel: delegation.grantorLabel || null,
  }
}
