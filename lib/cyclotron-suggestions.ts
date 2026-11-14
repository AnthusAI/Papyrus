import type { ReferenceRecord } from "./category-repository";
import type { RelevanceCuration, RelevanceDecisionView } from "./relevance-decisions";
import { safeId } from "./relevance-status";

export const SHADOW_AGREEMENT_SCHEMA = "cyclotron-shadow-agreement/v1";
export const MINIMUM_COMPARISONS_FOR_AGREEMENT = 10;

/** What the sweep recorded about the loop itself: whether it is on, when it last ran, why it stopped. */
export type CyclotronLoopState = {
  enabled: boolean;
  stoppedBecause: string | null;
  lastSweepAt: string | null;
  maxDecisionsPerDay: number | null;
};

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
  loop: CyclotronLoopState | null;
};

export type AgreementStripMeasurement = {
  comparisons: number;
  agreement: number | null;
  precision: number | null;
  recall: number | null;
  computedAt: string | null;
};

export type AgreementStripState =
  | { kind: "hidden" }
  | {
    kind: "not_enough" | "measured";
    measurement: AgreementStripMeasurement;
    needed: number;
    loop: CyclotronLoopState | null;
    stopReasonSentence: string | null;
  };

export function shadowAgreementPayloadId(cyclotronId: string): string {
  return `knowledge-raw-payload-cyclotron-shadow-agreement-${safeId(cyclotronId)}`;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseLoop(value: unknown): CyclotronLoopState | null {
  if (!value || typeof value !== "object") return null;
  const loop = value as Record<string, unknown>;
  if (typeof loop.enabled !== "boolean") return null;
  return {
    enabled: loop.enabled,
    stoppedBecause: typeof loop.stoppedBecause === "string" && loop.stoppedBecause ? loop.stoppedBecause : null,
    lastSweepAt: typeof loop.lastSweepAt === "string" ? loop.lastSweepAt : null,
    maxDecisionsPerDay: numberOrNull(loop.maxDecisionsPerDay),
  };
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
    loop: parseLoop(record.loop),
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
  disabled: "Suggestions are switched off in the settings, so none are being made.",
  "daily decision cap": "The last check reached the daily limit, so some references have no suggestion yet.",
};

/** The sentence an editor reads for a stop reason; unknown reasons are shown as given. */
export function stopReasonSentence(reason: string): string {
  return STOP_REASON_WORDS[reason] ?? `The last check stopped early: ${reason}.`;
}

/**
 * What the Live agreement strip shows. No payload hides it; under ten
 * comparisons the figures are withheld; a stop reason is always put in words.
 */
export function agreementStripState(agreement: ShadowAgreement | null): AgreementStripState {
  if (!agreement) return { kind: "hidden" };
  const loop = agreement.loop;
  return {
    kind: agreement.comparisons < MINIMUM_COMPARISONS_FOR_AGREEMENT ? "not_enough" : "measured",
    measurement: {
      comparisons: agreement.comparisons,
      agreement: agreement.agreement,
      precision: agreement.precision,
      recall: agreement.recall,
      computedAt: agreement.computedAt,
    },
    needed: MINIMUM_COMPARISONS_FOR_AGREEMENT,
    loop,
    stopReasonSentence: loop?.stoppedBecause ? stopReasonSentence(loop.stoppedBecause) : null,
  };
}

/** "Suggestions on" or "Suggestions off", the words the panel leads with. */
export function loopStateWords(loop: CyclotronLoopState): string {
  return loop.enabled ? "Suggestions on" : "Suggestions off";
}

/** The daily cap in words; no cap is said plainly. */
export function dailyCapWords(loop: CyclotronLoopState): string {
  return loop.maxDecisionsPerDay === null ? "No daily limit" : `Daily limit ${loop.maxDecisionsPerDay} decisions`;
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
 * Reference lineage ids whose latest vote was made by a signed-in person
 * (`curationActorKind` is `human`). Agent, Cyclotron and rule votes never appear
 * here, and neither does a reference a person decided before a later non-human change.
 */
export function referencesWithHumanLatestCuration(references: readonly ReferenceRecord[]): Set<string> {
  return new Set(references.filter((reference) => reference.curationActorKind === "human").map((reference) => reference.lineageId ?? reference.id));
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
  teachingLabelsSentence: string | null;
  primingExamplesSentence: string | null;
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
    teachingLabelsSentence: provenance.teachingLabels === null ? null : `Based on ${plural(provenance.teachingLabels, "decision")} that editors made themselves`,
    primingExamplesSentence: provenance.primingExamples === null ? null : `${plural(provenance.primingExamples, "example reference")} supplied as starting examples`,
    doctrineShortHash: provenance.doctrineFingerprint ? provenance.doctrineFingerprint.slice(0, SHORT_HASH_LENGTH) : null,
    modelVersion: decision.version === null ? null : `revision ${decision.version}`,
    decidedAt: decision.decidedAt,
  };
}

export function suggestionConfidenceWords(decision: RelevanceDecisionView): string {
  return decision.confidence === null ? "confidence unknown" : `${Math.round(decision.confidence * 100)}% sure`;
}

/** A curation recorded by an agent using a delegation a person granted. */
export type DelegatedCuration = {
  agent: string;
  person: string | null;
  instruction: string;
  delegationId: string;
  delegationShortId: string;
  /** What the backend does: a delegated curation is stamped human, so the person's label trains the cyclotron. */
  countsAsTrainingLabel: boolean;
};

const DELEGATION_ID_PREFIX = "curation-delegation-";
const DELEGATION_SHORT_ID_LENGTH = 8;

export function delegationShortId(delegationId: string): string {
  return delegationId.replace(DELEGATION_ID_PREFIX, "").slice(0, DELEGATION_SHORT_ID_LENGTH);
}

/**
 * Delegated curations by reference lineage, from each Reference's latest vote only.
 * The person is who set the status (`curationStatusUpdatedBy`); the agent is the delegation's relayedBy.
 */
export function delegatedCurationsByReference(references: readonly ReferenceRecord[]): Map<string, DelegatedCuration> {
  const delegated = new Map<string, DelegatedCuration>();
  for (const reference of references) {
    const delegation = parseMetadata(reference.curationDelegation);
    if (!Object.keys(delegation).length) continue;
    const delegationId = typeof delegation.delegationId === "string" ? delegation.delegationId : "";
    delegated.set(reference.lineageId ?? reference.id, {
      agent: typeof delegation.relayedBy === "string" && delegation.relayedBy ? delegation.relayedBy : "an agent",
      person: reference.curationStatusUpdatedBy?.trim() || null,
      instruction: typeof delegation.instruction === "string" ? delegation.instruction : "",
      delegationId,
      delegationShortId: delegationShortId(delegationId),
      countsAsTrainingLabel: reference.curationActorKind === "human",
    });
  }
  return delegated;
}
