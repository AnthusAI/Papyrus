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

/**
 * The star partition a Reference is in: "<corpusId>#stars#<n>" for a whole star rating of 1 to 5, null when it has none or no corpus.
 * It is not part of `referenceFeedKeys`: callers spread those keys on partial patches whose input may lack `starRating`, which would wrongly
 * clear it. A star write sets it (`setReferenceStars`); the index is sparse, so an unstarred Reference is in no star partition. It does not look
 * at the feed state: the reader drops a row with no `feedStateKey` (archived or superseded) instead.
 */
export function starFeedKeyFor(corpusId: string | null | undefined, stars: number | null | undefined): string | null {
  if (!corpusId || typeof stars !== "number" || !Number.isInteger(stars) || stars < 1 || stars > 5) return null;
  return `${corpusId}#stars#${stars}`;
}

/**
 * The medium partition a Reference is in: "<corpusId>#<medium>#<pending|accepted|rejected>" for a current, not archived Reference with a medium;
 * null otherwise. Python twin: `medium_feed_key` (the Python one also reads the medium off the address when none is stored; the writers here
 * use the stored medium, and `papyrus references backfill-medium` fills in the rest).
 */
export function referenceMediumFeedKey(reference: ReferenceFeedKeyInput & { medium?: string | null }): string | null {
  if (reference.versionState && reference.versionState !== "current") return null;
  if (!reference.corpusId || !reference.medium) return null;
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  if (status === "archived") return null;
  return `${reference.corpusId}#${reference.medium}#${status}`;
}

/** Verdicts after which no automatic attempt can capture a video: it leaves the content-needed list and stays in To capture for a person. */
export const SETTLED_CAPTURE_REASONS: readonly string[] = ["no_transcript", "unavailable", "unsupported_platform"];

/**
 * The content-needed partition: "<corpusId>#<medium>#needs_content#<pending|accepted|rejected>" for a current, not archived Reference with a medium whose
 * content is not captured in full (`captureState` empty, "none" or "thin"; "running" will finish by itself) and with no settled `captureReason`; null otherwise.
 * Python twin: `content_needed_key`. The writers here use the stored medium; `papyrus references backfill-medium` fills in the rest.
 */
export function referenceContentNeededKey(
  reference: ReferenceFeedKeyInput & { medium?: string | null; captureState?: string | null; captureReason?: string | null },
): string | null {
  const mediumKey = referenceMediumFeedKey(reference);
  if (!mediumKey || reference.captureState === "full" || reference.captureState === "running") return null;
  if (reference.captureReason && SETTLED_CAPTURE_REASONS.includes(reference.captureReason)) return null;
  const [corpusId, medium, status] = mediumKey.split("#");
  return `${corpusId}#${medium}#needs_content#${status}`;
}

/**
 * `{ mediumFeedKey }` for a vote or archive written as a patch, `{}` for a Reference that has no medium and no key, so an ordinary page's patch
 * names no new field. `changes` overrides the Reference's own values (the next `curationStatus`, the target `corpusId`). A held `contentNeededKey`
 * moves with the vote (same key, new status) or is cleared on archive; it needs no capture state (Python twin: `medium_key_patch`).
 */
export function referenceMediumKeyPatch(
  reference: ReferenceFeedKeyInput & { medium?: string | null; mediumFeedKey?: string | null; contentNeededKey?: string | null },
  changes: Partial<ReferenceFeedKeyInput> = {},
): { mediumFeedKey?: string | null; contentNeededKey?: string | null } {
  if (!reference.medium && !reference.mediumFeedKey) return {};
  const merged = { ...reference, ...changes };
  const patch: { mediumFeedKey?: string | null; contentNeededKey?: string | null } = { mediumFeedKey: referenceMediumFeedKey(merged) };
  const held = reference.contentNeededKey;
  if (held) {
    const medium = merged.medium ?? reference.mediumFeedKey?.split("#")[1] ?? null;
    const moved = medium ? referenceMediumFeedKey({ ...merged, medium }) : null;
    patch.contentNeededKey = moved ? `${held.slice(0, held.lastIndexOf("#"))}#${moved.slice(moved.lastIndexOf("#") + 1)}` : null;
  }
  return patch;
}

/** A pending row is in the public index only with a stored prediction at or above this. */
export const RECOMMENDED_FLOOR = 0.5;

export type ReferencePublicKeyInput = ReferenceFeedKeyInput & { feedArrivalAt?: string | null; publicFeedKey?: string | null };
export type ReferencePublicKeys = { publicFeedKey: string | null; publicOrderKey: string | null };

/** The stored prediction as a number in 0..1, or null: only a finite number counts, and a missing prediction is never a number. */
function storedProbability(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : null;
}

/**
 * The sparse keys a public block reads (docs/plans/public-blocks-from-indexes.md). Python twin: `public_feed_keys`; scripts/fixtures/public-feed-key-vectors.json
 * holds the vectors both test. Accepted: "<corpusId>#accepted" sorted "p<P>#<arrival>#<id>" ("n#..." when never scored). Pending with a stored prediction of
 * at least 0.5: "<corpusId>#recommended#<UTC day>". Anything else (rejected, archived, superseded, no corpus, no prediction, a prediction below 0.5): both null.
 * The stored `feedArrivalAt` wins over the derived arrival, as in Python.
 */
export function referencePublicFeedKeys(reference: ReferencePublicKeyInput, probability?: number | null): ReferencePublicKeys {
  const none: ReferencePublicKeys = { publicFeedKey: null, publicOrderKey: null };
  if (reference.versionState && reference.versionState !== "current") return none;
  if (!reference.corpusId) return none;
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const stored = storedProbability(probability ?? reference.predictedAcceptProbability);
  const arrival = instant(reference.feedArrivalAt) ?? referenceFeedArrivalAt(reference);
  if (status === "accepted") {
    return { publicFeedKey: `${reference.corpusId}#accepted`, publicOrderKey: stored === null ? `n#${arrival}#${reference.id}` : `p${stored.toFixed(6)}#${arrival}#${reference.id}` };
  }
  if (status === "pending" && stored !== null && stored >= RECOMMENDED_FLOOR) {
    return { publicFeedKey: `${reference.corpusId}#recommended#${arrival.slice(0, 10)}`, publicOrderKey: `p${stored.toFixed(6)}#${arrival}#${reference.id}` };
  }
  return none;
}

/**
 * The public keys for a vote or an archive written as a patch. `{}` for a row that neither has keys nor will have them, so a patch for an ordinary row
 * names no new field. `changes` overrides the Reference's own values (the next `curationStatus`, the target `corpusId`). Python twin: `public_key_patch`.
 */
export function referencePublicKeyPatch(reference: ReferencePublicKeyInput, changes: Partial<ReferenceFeedKeyInput> = {}): Partial<ReferencePublicKeys> {
  const wanted = referencePublicFeedKeys({ ...reference, ...changes });
  return wanted.publicFeedKey || reference.publicFeedKey ? wanted : {};
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
