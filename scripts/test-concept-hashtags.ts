import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { conceptHashtag, conceptHashtagLabel, conceptKeysForHashtag } from "../lib/wiki";

const vectors = JSON.parse(readFileSync(join(__dirname, "..", "features_backend", "fixtures", "concept-hashtags.json"), "utf8"));
const nodeKeys: string[] = vectors.nodeKeys;

for (const vector of vectors.hashtags) assert.equal(conceptHashtag(vector.nodeKey), vector.hashtag, vector.nodeKey);
for (const vector of vectors.labels) assert.equal(conceptHashtagLabel(vector.nodeKey, nodeKeys), vector.label, vector.nodeKey);
for (const vector of vectors.parse) assert.deepEqual(conceptKeysForHashtag(vector.text, nodeKeys), vector.candidates, vector.text);
assert.deepEqual(conceptKeysForHashtag(conceptHashtag("concept--voice-cloning"), nodeKeys), ["concept--voice-cloning"]);

console.log("concept hashtag tests passed");
