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
    state: "onboarding", rate: 1, reason: "Getting started: every suggestion is reviewed until suggestions earn a lower review rate.",
    auditFloor: 0.05, confidenceThreshold: 0.7, override: null,
    nextCheckAfterDecisions: 99,
    nextStep: "Steps down to 50% after 2 more windows of 100 decisions with accuracy on confident decisions of at least 85% (at least 20 reviewed) and a gap under 5 points between how sure suggestions say they are and how often they are right. Next check in 99 decisions.",
    expectedReviewsPerWeek: 1,
  },
  lastChange: null,
  pending: { decisionsAwaitingReview: 1, staleSince: null },
};

/**
 * What the Newsroom assumes until a decision names the cyclotron: the defaults
 * of the steering config's relevanceCyclotron block (src/papyrus_content/relevance_cyclotron.py).
 */
export const DEFAULT_RELEVANCE_CYCLOTRON = { id: "papyrus-relevance", labels: ["include", "exclude"] } as const;

/** The payload kind of a priming request; the sweep lists the cyclotron's payloads and filters on it. */
export const PRIMING_REQUEST_KIND = "cyclotron-priming-request";

/** The attachment role the sweep writes a request's outcome under. */
export const PRIMING_OUTCOME_ROLE = "priming_outcome";

/** The KnowledgeRawPayload an editor writes to ask the next sweep to prime the cyclotron with one URL. */
export function primingRequestPayloadId(cyclotronId: string, requestId: string): string {
  return `knowledge-raw-payload-cyclotron-priming-request-${safeId(cyclotronId)}-${safeId(requestId)}`;
}

export type PrimingRequest = {
  requestId: string;
  url: string;
  label: string;
  explanation: string;
  requestedBy: string;
  requestedAt: string;
};

export type PrimingOutcome =
  | { state: "applied"; version: number; at: string; itemId?: string }
  | { state: "failed"; message: string; at: string };

/** A saved request with the sweep's outcome, once there is one. */
export type PrimingRequestView = { request: PrimingRequest; outcome: PrimingOutcome | null };

export function buildPrimingRequest(
  input: { url: string; label: string; explanation?: string },
  requestedBy: string,
  labels: readonly string[],
  now: Date = new Date(),
  requestId: string = `${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
): PrimingRequest {
  let parsed: URL | null = null;
  try {
    parsed = new URL(input.url.trim());
  } catch {
    parsed = null;
  }
  if (!parsed || parsed.protocol !== "https:") throw new Error("Paste an https URL.");
  if (!labels.includes(input.label)) throw new Error(`Choose a label: ${labels.join(" or ")}.`);
  return {
    requestId,
    url: parsed.toString(),
    label: input.label,
    explanation: (input.explanation ?? "").trim(),
    requestedBy,
    requestedAt: now.toISOString(),
  };
}

export function isPrimingOutcome(value: unknown): value is PrimingOutcome {
  if (!value || typeof value !== "object") return false;
  const outcome = value as Record<string, unknown>;
  return (outcome.state === "applied" && typeof outcome.version === "number")
    || (outcome.state === "failed" && typeof outcome.message === "string");
}

/** In plain words: Adding, Added, or Couldn't add with the reason. */
export function primingStateText(view: PrimingRequestView): string {
  if (!view.outcome) return "Adding";
  return view.outcome.state === "applied"
    ? "Added"
    : `Couldn't add: ${view.outcome.message}`;
}
