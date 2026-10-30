/**
 * The keys the References page reads through (docs/reference-feed-indexes.md). The Python twin is
 * src/papyrus_content/reference_feed_keys.py; scripts/fixtures/reference-feed-key-vectors.json holds the vectors both test.
 *
 * `feedStateKey` is "<corpusId>#unrated" (pending) or "<corpusId>#rated" (accepted or rejected); a Reference that is not the current
 * version, or is archived, has none and is in neither feed. `predictionSortKey` is the Cyclotron's ORIGINAL P(accept), then arrival, then
 * id; a Reference nobody predicted sorts as 0.5. A vote changes `feedStateKey` and nothing else here.
 */
import { normalizeReferenceCurationStatus } from "./reference-policy";

export const UNDECIDED_PROBABILITY = 0.5;
const EPOCH = "1970-01-01T00:00:00.000Z";
const ARRIVAL_FIELDS = ["createdAt", "importedAt", "retrievedAt", "sourcePublishedAt", "versionCreatedAt"] as const;

export type ReferenceFeedKeyInput = {
  id: string;
  corpusId?: string | null;
  curationStatus?: string | null;
  versionState?: string | null;
  predictedAcceptProbability?: number | null;
  createdAt?: string | null;
  importedAt?: string | null;
  retrievedAt?: string | null;
  sourcePublishedAt?: string | null;
  versionCreatedAt?: string | null;
};

export type ReferenceFeedKeys = {
  feedStateKey: string | null;
  feedArrivalAt: string;
  predictionSortKey: string;
};

function instant(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null;
}

export function referenceFeedArrivalAt(reference: ReferenceFeedKeyInput): string {
  for (const field of ARRIVAL_FIELDS) {
    const found = instant(reference[field]);
    if (found) return found;
  }
  return EPOCH;
}

export function referenceFeedStateKey(reference: ReferenceFeedKeyInput): string | null {
  if (reference.versionState && reference.versionState !== "current") return null;
  if (!reference.corpusId) return null;
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  if (status === "archived") return null;
  return `${reference.corpusId}#${status === "pending" ? "unrated" : "rated"}`;
}

export function predictionSortKeyFor(probability: number | null | undefined, arrival: string, referenceId: string): string {
  const chosen = probability === null || probability === undefined ? UNDECIDED_PROBABILITY : Math.min(1, Math.max(0, probability));
  return `${chosen.toFixed(6)}#${arrival}#${referenceId}`;
}

/** The three feed keys for a Reference as it stands. `probability` overrides the one stored on it. */
export function referenceFeedKeys(reference: ReferenceFeedKeyInput, probability?: number | null): ReferenceFeedKeys {
  const arrival = referenceFeedArrivalAt(reference);
  return {
    feedStateKey: referenceFeedStateKey(reference),
    feedArrivalAt: arrival,
    predictionSortKey: predictionSortKeyFor(probability ?? reference.predictedAcceptProbability, arrival, reference.id),
  };
}
