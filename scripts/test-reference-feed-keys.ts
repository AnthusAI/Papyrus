import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { referenceContentNeededKey, referenceFeedKeys, referenceMediumFeedKey, referenceMediumKeyPatch, referencePublicFeedKeys, referencePublicKeyPatch, starFeedKeyFor, type ReferenceFeedKeyInput, type ReferencePublicKeyInput } from "../lib/reference-feed-keys";

type Vector = { name: string; reference: ReferenceFeedKeyInput & { starRating?: number | null; medium?: string | null; captureState?: string | null; captureReason?: string | null }; mediumFeedKey?: string | null; contentNeededKey?: string | null; keys: ReturnType<typeof referenceFeedKeys>; starFeedKey?: string | null };
const vectors = JSON.parse(readFileSync(join(process.cwd(), "scripts/fixtures/reference-feed-key-vectors.json"), "utf8")) as Vector[];

for (const vector of vectors) {
  assert.deepEqual(referenceFeedKeys(vector.reference), vector.keys, vector.name);   // never carries the star key: callers spread it on partial patches
  if ("starFeedKey" in vector) assert.equal(starFeedKeyFor(vector.reference.corpusId, vector.reference.starRating), vector.starFeedKey, vector.name);
  if ("mediumFeedKey" in vector) assert.equal(referenceMediumFeedKey(vector.reference), vector.mediumFeedKey, vector.name);
  if ("contentNeededKey" in vector) assert.equal(referenceContentNeededKey(vector.reference), vector.contentNeededKey, vector.name);
}
// A held content-needed key moves with a vote and leaves on archive; a vote on a video that holds none names no content field.
const held = { id: "r", corpusId: "c", curationStatus: "pending", medium: "video", mediumFeedKey: "c#video#pending", contentNeededKey: "c#video#needs_content#pending" };
assert.deepEqual(referenceMediumKeyPatch(held, { curationStatus: "accepted" }), { mediumFeedKey: "c#video#accepted", contentNeededKey: "c#video#needs_content#accepted" });
assert.deepEqual(referenceMediumKeyPatch(held, { curationStatus: "archived" }), { mediumFeedKey: null, contentNeededKey: null });
assert.deepEqual(referenceMediumKeyPatch({ ...held, contentNeededKey: null }, { curationStatus: "accepted" }), { mediumFeedKey: "c#video#accepted" });
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

// The public keys (the attributes the public blocks' index will read): the same vectors the Python twin is tested against.
type PublicVector = { name: string; reference: ReferencePublicKeyInput; publicKeys: { publicFeedKey: string | null; publicOrderKey: string | null } };
const publicVectors = JSON.parse(readFileSync(join(process.cwd(), "scripts/fixtures/public-feed-key-vectors.json"), "utf8")) as PublicVector[];
for (const vector of publicVectors) assert.deepEqual(referencePublicFeedKeys(vector.reference), vector.publicKeys, vector.name);
// A prediction that is not a finite number is never a number: a pending row without one is not public.
for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
  assert.deepEqual(referencePublicFeedKeys({ id: "r", corpusId: "c", curationStatus: "pending", createdAt: "2026-10-28T12:00:00Z", predictedAcceptProbability: bad }), { publicFeedKey: null, publicOrderKey: null }, String(bad));
}
// A vote moves the row between the partitions and keeps its place in the order; an ordinary row's patch names nothing.
const votable: ReferencePublicKeyInput = { id: "r", corpusId: "c", curationStatus: "pending", createdAt: "2026-10-28T12:00:00Z", predictedAcceptProbability: 0.7, publicFeedKey: "c#recommended#2026-10-28" };
assert.deepEqual(referencePublicKeyPatch(votable, { curationStatus: "accepted" }), { publicFeedKey: "c#accepted", publicOrderKey: "p0.700000#2026-10-28T12:00:00.000Z#r" });
assert.deepEqual(referencePublicKeyPatch(votable, { curationStatus: "rejected" }), { publicFeedKey: null, publicOrderKey: null });
assert.deepEqual(referencePublicKeyPatch(votable, { curationStatus: "archived" }), { publicFeedKey: null, publicOrderKey: null });
const lowScored: ReferencePublicKeyInput = { id: "s", corpusId: "c", curationStatus: "pending", createdAt: "2026-10-28T12:00:00Z", predictedAcceptProbability: 0.3 };
assert.deepEqual(referencePublicKeyPatch(lowScored, { curationStatus: "accepted" }), { publicFeedKey: "c#accepted", publicOrderKey: "p0.300000#2026-10-28T12:00:00.000Z#s" });
assert.deepEqual(referencePublicKeyPatch(lowScored, { curationStatus: "rejected" }), {});
assert.deepEqual(referenceFeedKeys(votable), { feedStateKey: "c#unrated", feedArrivalAt: "2026-10-28T12:00:00.000Z", predictionSortKey: "0.700000#2026-10-28T12:00:00.000Z#r" }, "the feed keys never carry the public keys: callers spread them on partial patches");

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
// And the sparse content-needed index (the transcript worker's list): one partition per corpus, medium and status, read by arrival.
const contentPartition = referenceType.split("\n").find((line) => /^\s+contentNeededKey: String/.test(line)) ?? "";
assert.match(contentPartition, /@index\(sortKeyFields: \["feedArrivalAt"\], queryField: "listReferencesByContentNeededAndArrival"\)/, "content-needed index");
// The public-blocks attributes, and the one sparse index over two of them (PPY-7f1e54): partition publicFeedKey, sort publicOrderKey, and no other new index.
for (const attribute of ["publicFeedKey", "publicOrderKey", "cardImage", "cardSummary", "cardSiteName", "cardPageTitle"]) {
  assert.match(referenceType, new RegExp(`\\s${attribute}: String`), `${attribute} is on Reference`);
}
const publicPartition = referenceType.split("\n").find((line) => /^\s+publicFeedKey: String/.test(line)) ?? "";
assert.match(publicPartition, /@index\(sortKeyFields: \["publicOrderKey"\], queryField: "listReferencesByPublicFeed"\)/, "public index");
assert.equal((referenceType.match(/@index\(/g) ?? []).length, 16, "one index was added to the fifteen Reference had: one new index per table per deploy");
assert.match(referenceType, /predictedAcceptProbability: Float/);
assert.match(referenceType, /predictionDecidedAt: AWSDateTime/);
assert.match(referenceType, /feedArrivalAt: AWSDateTime/);
console.log(`reference feed keys ok (${vectors.length} vectors)`);
