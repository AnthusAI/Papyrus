/**
 * Code-local trust contract for a site-hosted shared chat adapter.
 *
 * This module does not verify JWT signatures and is not an HTTP endpoint. The
 * hosting server must inject a real verifier and authoritative membership
 * resolver. Never construct VerifiedChatCredential from request JSON.
 */

export type TokenUse = string;

/** Claims returned only after the injected host verifier has validated the JWT. */
export interface VerifiedChatCredential {
  subject: string;
  issuer: string;
  audiences: readonly string[];
  clientId?: string;
  tokenUse?: TokenUse;
  expiresAtEpochSeconds: number;
  notBeforeEpochSeconds?: number;
  issuedAtEpochSeconds?: number;
}

export interface AudienceRule {
  /** Explicitly choose which JWT claim is authoritative for this host. */
  claim: "aud" | "client_id";
  expectedValue: string;
}

export interface ChatHostTrustProfile {
  issuer: string;
  audienceRule: AudienceRule;
  /** Must be configured by the host after verifying its actual token contract. */
  acceptedTokenUses: readonly TokenUse[];
  configuredSiteId: string;
  clockSkewSeconds?: number;
}

export interface ChatRequest {
  authorization?: string;
  channelId: string;
  idempotencyKey: string;
  message: { text: string; authorSub?: string; accountId?: string; siteId?: string };
}

export interface ChatMembership {
  accountId: string;
  siteId: string;
  editorSub: string;
  active: boolean;
}

export interface TranscriptOwner {
  accountId: string;
  siteId: string;
  editorSub: string;
  channelId: string;
}

export interface SharedChatAdmissionDependencies {
  trust: ChatHostTrustProfile;
  nowEpochSeconds?: () => number;
  verifyCredential: (rawCredential: string) => Promise<VerifiedChatCredential | null>;
  resolveMembership: (subject: string, configuredSiteId: string) => Promise<ChatMembership | null>;
  resolveTranscriptOwner: (channelId: string) => Promise<TranscriptOwner | null>;
}

export interface AdmittedChatMessage {
  owner: TranscriptOwner;
  idempotencyKey: string;
  /** Stable canonical representation used for payload-reuse detection. */
  payloadFingerprint: string;
}

export class ChatAdmissionError extends Error {
  readonly code: "unauthorized" | "forbidden" | "invalid_request" | "idempotency_conflict";

  constructor(code: ChatAdmissionError["code"]) {
    super(code);
    this.name = "ChatAdmissionError";
    this.code = code;
  }
}

const reject = (code: ChatAdmissionError["code"]): never => { throw new ChatAdmissionError(code); };

function bearerToken(value: string | undefined): string {
  const match = value?.match(/^Bearer ([^\s]+)$/i);
  if (!match) return reject("unauthorized");
  return match[1];
}

function assertCredential(credential: VerifiedChatCredential, trust: ChatHostTrustProfile, now: number): void {
  const skew = Math.max(0, trust.clockSkewSeconds ?? 0);
  if (!trust.issuer || credential.issuer !== trust.issuer) reject("unauthorized");
  if (!trust.acceptedTokenUses.length || !credential.tokenUse || !trust.acceptedTokenUses.includes(credential.tokenUse)) reject("unauthorized");
  if (!Number.isFinite(credential.expiresAtEpochSeconds) || now - skew >= credential.expiresAtEpochSeconds) reject("unauthorized");
  if (credential.notBeforeEpochSeconds !== undefined && now + skew < credential.notBeforeEpochSeconds) reject("unauthorized");
  if (credential.issuedAtEpochSeconds !== undefined && now + skew < credential.issuedAtEpochSeconds) reject("unauthorized");

  const audienceMatches = trust.audienceRule.claim === "aud"
    ? credential.audiences.includes(trust.audienceRule.expectedValue)
    : credential.clientId === trust.audienceRule.expectedValue;
  if (!audienceMatches) reject("unauthorized");
}

/** Authenticate, derive the current host membership, and enforce private channel ownership. */
export async function admitSharedChatMessage(
  request: ChatRequest,
  dependencies: SharedChatAdmissionDependencies,
): Promise<AdmittedChatMessage> {
  if (!request.channelId || !request.message.text.trim() || !/^[A-Za-z0-9._~-]{16,128}$/.test(request.idempotencyKey)) {
    return reject("invalid_request");
  }

  const rawCredential = bearerToken(request.authorization);
  const credential = await dependencies.verifyCredential(rawCredential);
  if (!credential) return reject("unauthorized");
  const now = (dependencies.nowEpochSeconds ?? (() => Date.now() / 1000))();
  assertCredential(credential, dependencies.trust, now);

  const membership = await dependencies.resolveMembership(credential.subject, dependencies.trust.configuredSiteId);
  if (!membership || !membership.active || membership.editorSub !== credential.subject || membership.siteId !== dependencies.trust.configuredSiteId) {
    return reject("forbidden");
  }
  if ((request.message.authorSub && request.message.authorSub !== membership.editorSub)
    || (request.message.accountId && request.message.accountId !== membership.accountId)
    || (request.message.siteId && request.message.siteId !== membership.siteId)) {
    return reject("forbidden");
  }

  const expectedOwner: TranscriptOwner = {
    accountId: membership.accountId,
    siteId: membership.siteId,
    editorSub: membership.editorSub,
    channelId: request.channelId,
  };
  const actualOwner = await dependencies.resolveTranscriptOwner(request.channelId);
  if (!actualOwner || actualOwner.accountId !== expectedOwner.accountId || actualOwner.siteId !== expectedOwner.siteId
    || actualOwner.editorSub !== expectedOwner.editorSub || actualOwner.channelId !== expectedOwner.channelId) {
    return reject("forbidden");
  }

  return {
    owner: expectedOwner,
    idempotencyKey: request.idempotencyKey,
    payloadFingerprint: JSON.stringify([request.channelId, request.message.text]),
  };
}

export interface IdempotencyRequest<T> {
  /** Storage must atomically scope key by the derived owner and operation. */
  scope: string;
  key: string;
  payloadFingerprint: string;
  run: () => Promise<T>;
}

/**
 * Store contract for replay-safe writes. Production implementations must be
 * atomic/durable (for example conditional put + canonical result); this module
 * deliberately supplies no in-memory production store.
 */
export interface ChatIdempotencyStore {
  executeOnce<T>(request: IdempotencyRequest<T>): Promise<T>;
}

export function runAdmittedChatMessage<T>(
  admission: AdmittedChatMessage,
  store: ChatIdempotencyStore,
  operation: () => Promise<T>,
): Promise<T> {
  const { accountId, siteId, editorSub, channelId } = admission.owner;
  return store.executeOnce({
    scope: JSON.stringify(["chat-message", accountId, siteId, editorSub, channelId]),
    key: admission.idempotencyKey,
    payloadFingerprint: admission.payloadFingerprint,
    run: operation,
  });
}
