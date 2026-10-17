import type { CyclotronStatus } from "cyclotron/cyclotron-status";
import { isCyclotronStatus } from "cyclotron/cyclotron-status";

/** The KnowledgeRawPayload the decide-relevance sweep writes the status snapshot to. */
export function cyclotronStatusPayloadId(cyclotronId: string): string {
  return `knowledge-raw-payload-cyclotron-status-${safeId(cyclotronId)}`;
}

/** The KnowledgeRawPayload an editor writes to ask for a manual review rate. */
export function reviewRateRequestPayloadId(cyclotronId: string): string {
  return `knowledge-raw-payload-cyclotron-review-rate-request-${safeId(cyclotronId)}`;
}

/** Mirrors Python's ids.safe_id so both sides name the same record. */
export function safeId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 140);
}

export type ReviewRateRequest =
  | { rate: number; expiresAt: string; setBy: string; requestedAt: string }
  | { clear: true; setBy: string; requestedAt: string };

export function buildReviewRateRequest(
  choice: { rate: number; days: number } | { clear: true },
  setBy: string,
  now: Date = new Date(),
): ReviewRateRequest {
  const requestedAt = now.toISOString();
  if ("clear" in choice) return { clear: true, setBy, requestedAt };
  if (!(choice.rate >= 0 && choice.rate <= 1)) throw new Error("A review rate is between 0% and 100%.");
  if (!(choice.days >= 1)) throw new Error("A manual rate lasts at least one day.");
  const expiresAt = new Date(now.getTime() + choice.days * 24 * 60 * 60 * 1000).toISOString();
  return { rate: choice.rate, expiresAt, setBy, requestedAt };
}

/** The newest valid snapshot among a payload's attachments. */
export function latestCyclotronStatus(payloads: Array<{ json: unknown; updatedAt?: string | null }>): CyclotronStatus | null {
  const valid = payloads
    .filter((payload) => isCyclotronStatus(payload.json))
    .sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
  return valid.length ? (valid[0].json as CyclotronStatus) : null;
}

/** What demo mode shows: an onboarding cyclotron that has made one decision. */
export const DEMO_CYCLOTRON_STATUS: CyclotronStatus = {
  schema: "cyclotron-status/v1",
  cyclotron: { id: "papyrus-relevance", classifier: "relevant", version: 1, refits: 0, fingerprint: "demo" },
  asOf: "2026-05-16T12:00:00.000Z",
  alignment: {
    window: 200, labels: 0, accuracy: null, precision: null, recall: null,
    positiveLabel: "include", measuredOn: "reviews selected by the cyclotron",
  },
  calibration: { saysSure: null, isRight: null, gapPoints: null, curve: [] },
  reviewRate: {
    state: "onboarding", rate: 1, reason: "Onboarding: every decision is reviewed until the cyclotron earns a lower rate.",
    auditFloor: 0.05, confidenceThreshold: 0.7, override: null,
    nextCheckAfterDecisions: 99,
    nextStep: "Steps down to 50% after 2 more windows of 100 decisions with accuracy on confident decisions of at least 85% (at least 20 reviewed) and a calibration gap under 5 points. Next check in 99 decisions.",
    expectedReviewsPerWeek: 1,
  },
  lastChange: null,
  pending: { decisionsAwaitingReview: 1, staleSince: null },
};
