import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { referenceFeedKeys, referenceMediumFeedKey, referenceMediumKeyPatch, starFeedKeyFor, type ReferenceFeedKeyInput } from "../lib/reference-feed-keys";

type Vector = { name: string; reference: ReferenceFeedKeyInput & { starRating?: number | null; medium?: string | null }; mediumFeedKey?: string | null; keys: ReturnType<typeof referenceFeedKeys>; starFeedKey?: string | null };
const vectors = JSON.parse(readFileSync(join(process.cwd(), "scripts/fixtures/reference-feed-key-vectors.json"), "utf8")) as Vector[];

for (const vector of vectors) {
  assert.deepEqual(referenceFeedKeys(vector.reference), vector.keys, vector.name);   // never carries the star key: callers spread it on partial patches
  if ("starFeedKey" in vector) assert.equal(starFeedKeyFor(vector.reference.corpusId, vector.reference.starRating), vector.starFeedKey, vector.name);
  if ("mediumFeedKey" in vector) assert.equal(referenceMediumFeedKey(vector.reference), vector.mediumFeedKey, vector.name);
}
// The medium key patch names a field only for a Reference that has a medium or a key: an ordinary page's patch stays as it was.
assert.deepEqual(referenceMediumKeyPatch({ id: "r", corpusId: "c", curationStatus: "pending" }, { curationStatus: "accepted" }), {});
assert.deepEqual(referenceMediumKeyPatch({ id: "r", corpusId: "c", curationStatus: "pending", medium: "video" }, { curationStatus: "accepted" }), { mediumFeedKey: "c#video#accepted" });
assert.deepEqual(referenceMediumKeyPatch({ id: "r", corpusId: "c", curationStatus: "accepted", medium: "video" }, { curationStatus: "archived" }), { mediumFeedKey: null });
assert.deepEqual(referenceMediumKeyPatch({ id: "r", corpusId: "c", curationStatus: "accepted", mediumFeedKey: "c#video#accepted" }, { curationStatus: "pending" }), { mediumFeedKey: null });
assert.equal(starFeedKeyFor("c", undefined), null);
assert.equal(starFeedKeyFor("c", 0), null);
assert.equal(starFeedKeyFor("c", 6), null);
assert.equal(starFeedKeyFor("c", Number.NaN), null);
assert.equal(starFeedKeyFor(null, 3), null);

// Predictions reads the index newest-key-first: the highest P(accept) first, then the newest arrival.
const keyed = (id: string, probability: number | null, createdAt: string) =>
  referenceFeedKeys({ id, corpusId: "c", curationStatus: "pending", createdAt, predictedAcceptProbability: probability }).predictionSortKey;
const ranked = [
  keyed("a", 0.2, "2026-10-28T09:00:00Z"),
  keyed("b", 0.9, "2026-10-28T08:00:00Z"),
  keyed("c", null, "2026-10-28T10:00:00Z"),
  keyed("d", 0.9, "2026-10-28T11:00:00Z"),
].sort().reverse();
assert.deepEqual(ranked.map((key) => key.split("#").pop()), ["d", "b", "c", "a"], "Predictions: 0.9 newest, 0.9 older, unpredicted, predicted Reject");

// A vote moves the Reference between the feeds and leaves its prediction key alone.
const before = referenceFeedKeys({ id: "r", corpusId: "c", curationStatus: "pending", createdAt: "2026-10-28T09:00:00Z", predictedAcceptProbability: 0.7 });
const after = referenceFeedKeys({ id: "r", corpusId: "c", curationStatus: "rejected", createdAt: "2026-10-28T09:00:00Z", predictedAcceptProbability: 0.7 });
assert.equal(before.feedStateKey, "c#unrated");
assert.equal(after.feedStateKey, "c#rated");
assert.equal(after.predictionSortKey, before.predictionSortKey);
// The deployed schema has the two indexes the page pages through, both partitioned by the feed state, with the right sort keys.
const generated = schema.transform().schema;
const referenceType = generated.slice(generated.indexOf("type Reference @model"), generated.indexOf("type ReferenceAttachment"));
const partition = referenceType.split("\n").find((line) => /^\s+feedStateKey: String/.test(line)) ?? "";
assert.match(partition, /@index\(sortKeyFields: \["predictionSortKey"\], queryField: "listReferencesByFeedStateAndPrediction"\)/, "Predictions index");
assert.match(partition, /@index\(sortKeyFields: \["feedArrivalAt"\], queryField: "listReferencesByFeedStateAndArrival"\)/, "Newest index");
// And the sparse star index: one partition per star level, read by arrival.
const starPartition = referenceType.split("\n").find((line) => /^\s+starFeedKey: String/.test(line)) ?? "";
assert.match(starPartition, /@index\(sortKeyFields: \["feedArrivalAt"\], queryField: "listReferencesByStarFeedAndArrival"\)/, "star index");
// And the sparse medium index: one partition per corpus, medium and status, read by arrival.
const mediumPartition = referenceType.split("\n").find((line) => /^\s+mediumFeedKey: String/.test(line)) ?? "";
assert.match(mediumPartition, /@index\(sortKeyFields: \["feedArrivalAt"\], queryField: "listReferencesByMediumFeedAndArrival"\)/, "medium index");
assert.match(referenceType, /predictedAcceptProbability: Float/);
assert.match(referenceType, /predictionDecidedAt: AWSDateTime/);
assert.match(referenceType, /feedArrivalAt: AWSDateTime/);
console.log(`reference feed keys ok (${vectors.length} vectors)`);
