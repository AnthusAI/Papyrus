import type { MessageRecord } from "./category-repository";
import type { RelevanceCuration, RelevanceDecisionView } from "./relevance-decisions";
import { safeId } from "./relevance-status";

export const SHADOW_AGREEMENT_SCHEMA = "cyclotron-shadow-agreement/v1";
export const MINIMUM_COMPARISONS_FOR_AGREEMENT = 10;

/** The live-agreement payload the sweep writes: suggestions compared with later human decisions. */
export type ShadowAgreement = {
  schema: typeof SHADOW_AGREEMENT_SCHEMA;
  comparisons: number;
  agreement: number | null;
  precision: number | null;
  recall: number | null;
  confusion: Record<string, unknown> | null;
  computedAt: string | null;
  positiveLabel: string | null;
  /** Optional: false when the steering config switched the loop off. */
  enabled: boolean | null;
  /** Optional: why the last sweep stopped early, for example "daily decision cap". */
  stoppedBecause: string | null;
};

export type AgreementStripState =
  | { kind: "hidden" }
  | { kind: "stopped"; reason: string; measurement: AgreementStripMeasurement | null }
  | { kind: "not_enough"; comparisons: number; needed: number; computedAt: string | null; reason: null }
  | { kind: "measured"; measurement: AgreementStripMeasurement; reason: null };

export type AgreementStripMeasurement = {
  comparisons: number;
  agreement: number | null;
  precision: number | null;
  recall: number | null;
  computedAt: string | null;
};

export function shadowAgreementPayloadId(cyclotronId: string): string {
  return `knowledge-raw-payload-cyclotron-shadow-agreement-${safeId(cyclotronId)}`;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A shadow-agreement payload, or null for any other JSON. */
export function parseShadowAgreement(json: unknown): ShadowAgreement | null {
  if (!json || typeof json !== "object") return null;
  const record = json as Record<string, unknown>;
  if (record.schema !== SHADOW_AGREEMENT_SCHEMA) return null;
  return {
    schema: SHADOW_AGREEMENT_SCHEMA,
    comparisons: numberOrNull(record.comparisons) ?? 0,
    agreement: numberOrNull(record.agreement),
    precision: numberOrNull(record.precision),
    recall: numberOrNull(record.recall),
    confusion: record.confusion && typeof record.confusion === "object" ? (record.confusion as Record<string, unknown>) : null,
    computedAt: typeof record.computedAt === "string" ? record.computedAt : null,
    positiveLabel: typeof record.positiveLabel === "string" ? record.positiveLabel : null,
    enabled: typeof record.enabled === "boolean" ? record.enabled : null,
    stoppedBecause: typeof record.stoppedBecause === "string" && record.stoppedBecause ? record.stoppedBecause : null,
  };
}

/** The newest valid payload among a payload owner's attachments. */
export function latestShadowAgreement(payloads: Array<{ json: unknown; updatedAt?: string | null }>): ShadowAgreement | null {
  const valid = payloads
    .map((payload) => ({ agreement: parseShadowAgreement(payload.json), updatedAt: payload.updatedAt }))
    .filter((entry): entry is { agreement: ShadowAgreement; updatedAt: string | null | undefined } => entry.agreement !== null)
    .sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
  return valid.length ? valid[0].agreement : null;
}

const STOP_REASON_WORDS: Record<string, string> = {
  disabled: "The relevance cyclotron is switched off in the steering config, so it is making no suggestions.",
  "daily decision cap": "The last sweep stopped at the daily decision cap, so some references have no suggestion yet.",
};

/** The sentence an editor reads for a stop reason; unknown reasons are shown as given. */
export function stopReasonSentence(reason: string): string {
  return STOP_REASON_WORDS[reason] ?? `The last sweep stopped early: ${reason}.`;
}

/**
 * What the Live agreement strip shows. No payload and no stop reason hides it;
 * a stop reason always shows; under ten comparisons the numbers are withheld.
 */
export function agreementStripState(agreement: ShadowAgreement | null): AgreementStripState {
  if (!agreement) return { kind: "hidden" };
  const measurement: AgreementStripMeasurement = {
    comparisons: agreement.comparisons,
    agreement: agreement.agreement,
    precision: agreement.precision,
    recall: agreement.recall,
    computedAt: agreement.computedAt,
  };
  const reason = agreement.enabled === false ? "disabled" : agreement.stoppedBecause;
  if (reason) {
    return { kind: "stopped", reason, measurement: agreement.comparisons >= MINIMUM_COMPARISONS_FOR_AGREEMENT ? measurement : null };
  }
  if (agreement.comparisons < MINIMUM_COMPARISONS_FOR_AGREEMENT) {
    return { kind: "not_enough", comparisons: agreement.comparisons, needed: MINIMUM_COMPARISONS_FOR_AGREEMENT, computedAt: agreement.computedAt, reason: null };
  }
  return { kind: "measured", measurement, reason: null };
}

export function formatPercentage(fraction: number | null): string {
  return fraction === null ? "not measured" : `${Math.round(fraction * 100)}%`;
}

function parseMetadata(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Reference lineage ids whose latest curation Message was made by a signed-in
 * person. Agent and classifier status changes never appear here, and neither
 * does a reference a person decided before a later non-human change.
 */
export function referencesWithHumanLatestCuration(messages: MessageRecord[]): Set<string> {
  const latestByReference = new Map<string, { createdAt: string; human: boolean }>();
  for (const message of messages) {
    if (message.messageKind !== "reference_curation") continue;
    const metadata = parseMetadata(message.metadata);
    const lineageId = typeof metadata.referenceLineageId === "string" ? metadata.referenceLineageId : "";
    if (!lineageId) continue;
    const seen = latestByReference.get(lineageId);
    if (seen && seen.createdAt >= message.createdAt) continue;
    latestByReference.set(lineageId, { createdAt: message.createdAt, human: metadata.actorKind === "human" });
  }
  return new Set([...latestByReference].filter(([, entry]) => entry.human).map(([lineageId]) => lineageId));
}

export type SuggestionChoice = "agree" | "overrule";

/**
 * The accept or reject an editor's click becomes. Agreeing does what the
 * suggestion implies; overruling does the opposite. Both are the ordinary
 * curation actions, tied to the suggestion they answered.
 */
export function curationForSuggestionChoice(decision: RelevanceDecisionView, choice: SuggestionChoice): RelevanceCuration {
  const suggestsAccept = decision.positiveLabel !== null && decision.label === decision.positiveLabel;
  const accept = choice === "agree" ? suggestsAccept : !suggestsAccept;
  return {
    action: accept ? "accept" : "reject",
    reasonCode: null,
    note: null,
    decisionRelationId: decision.decisionRelationId,
    shareable: false,
  };
}

export type ProvenanceSummary = {
  teachingLabelsSentence: string;
  primingExamplesSentence: string;
  doctrineShortHash: string | null;
  modelVersion: string | null;
  decidedAt: string | null;
};

const SHORT_HASH_LENGTH = 8;

/** The facts the "How this suggestion was made" block lists; null when the decision recorded no provenance. */
export function provenanceSummary(decision: RelevanceDecisionView): ProvenanceSummary | null {
  const provenance = decision.provenance;
  if (!provenance) return null;
  const plural = (count: number, singular: string) => `${count} ${singular}${count === 1 ? "" : "s"}`;
  return {
    teachingLabelsSentence: `Taught by ${plural(provenance.teachingLabels, "label")} that editors set themselves`,
    primingExamplesSentence: `${plural(provenance.primingExamples, "priming example")} supplied as starting examples`,
    doctrineShortHash: provenance.doctrineFingerprint ? provenance.doctrineFingerprint.slice(0, SHORT_HASH_LENGTH) : null,
    modelVersion: decision.version === null ? null : `version ${decision.version}`,
    decidedAt: decision.decidedAt,
  };
}

export function suggestionConfidenceWords(decision: RelevanceDecisionView): string {
  return decision.confidence === null ? "confidence unknown" : `${Math.round(decision.confidence * 100)}% sure`;
}
