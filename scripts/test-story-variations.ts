/** Story variations, the pure part (lib/story-variations.ts): reading a row, where connections link, and what accepting writes onto the Story. */
import assert from "node:assert/strict";
import test from "node:test";
import { acceptedVariation, bodyWithVariation, changeReasonFor, connectionHref, frontMatterWithVariation, readVariation, sortVariations, variationIdOf, waysText } from "../lib/story-variations";

const row = {
  id: "variation-1", storyLineageId: "item-1", variationNumber: 2, status: "offered", point: "A point.", headline: "A headline", deck: "A deck.", bodyMarkus: null, section: null,
  connections: JSON.stringify([{ kind: "reference", id: "ref 1", title: "A Reference", how: "Linked by an editor" }, { kind: "story", id: "item-2", title: "A Story" }, { kind: "concept", id: "c-1", title: "#a-concept", how: "" }, { kind: "bogus", id: "x", title: "Nope" }, { kind: "story", id: "", title: "No id" }]),
  origin: "generated", pointCheck: JSON.stringify({ verdict: "adds", claim: "A claim." }), decidedByLabel: null, decidedAt: null, decisionReason: null,
};

test("a row is read with its connections and point check as data, and a connection with no kind, id or title is left out", () => {
  const read = readVariation(row);
  assert.deepEqual(read.connections.map((entry) => [entry.kind, entry.id, entry.how]), [["reference", "ref 1", "Linked by an editor"], ["story", "item-2", null], ["concept", "c-1", null]]);
  assert.deepEqual(read.pointCheck, { verdict: "adds", claim: "A claim.", reason: null });
  assert.equal(readVariation({ ...row, connections: [{ kind: "story", id: "s", title: "Already data" }], pointCheck: null, status: "weird" }).status, "offered");
});

test("connections link to the Reference, the Story and the concept", () => {
  assert.equal(connectionHref({ kind: "reference", id: "ref 1" }), "/newsroom/references/ref%201");
  assert.equal(connectionHref({ kind: "story", id: "item-2" }), "/newsroom/articles/item-2");
  assert.equal(connectionHref({ kind: "concept", id: "c-1" }), "/newsroom/concepts?node=c-1");
});

test("variations stay in the order they were offered and the accepted one is found", () => {
  const rows = [{ ...readVariation(row), variationNumber: 3 }, { ...readVariation(row), id: "v2", variationNumber: 1, status: "accepted" as const }];
  assert.deepEqual(sortVariations(rows).map((entry) => entry.variationNumber), [1, 3]);
  assert.equal(acceptedVariation(rows)?.id, "v2");
  assert.equal(waysText(1), "1 way to connect this");
  assert.equal(waysText(3), "3 ways to connect this");
});

test("accepting writes the headline as title, the deck, and where the wording came from, keeping every other line and comment", () => {
  const front = "# the idea\ntitle: Old\ndeck: Old deck\nsection: tools\ngenerated:\n  origin: monitor-stories # kept\n";
  const written = frontMatterWithVariation(front, readVariation(row));
  assert.match(written, /^title: A headline$/m);
  assert.match(written, /^deck: A deck\.$/m);
  assert.match(written, /^variationId: variation-1$/m);
  assert.match(written, /# the idea/);
  assert.match(written, /origin: monitor-stories # kept/);
  assert.match(written, /^section: tools$/m);
  assert.equal(variationIdOf(written), "variation-1");
  assert.equal(variationIdOf(front), null);
});

test("a variation with no deck leaves the Story's deck, and a second accept replaces the variation id", () => {
  const first = frontMatterWithVariation("title: Old\ndeck: Old deck\n", { id: "v1", headline: "One", deck: null });
  assert.match(first, /^deck: Old deck$/m);
  const second = frontMatterWithVariation(first, { id: "v2", headline: "Two", deck: "Deck two." });
  assert.equal(variationIdOf(second), "v2");
  assert.match(second, /^title: Two$/m);
  assert.equal((second.match(/variationId/g) ?? []).length, 1);
});

test("front matter that cannot be read is never overwritten, and an empty one gets the three keys", () => {
  assert.throws(() => frontMatterWithVariation("title: [unclosed", { id: "v", headline: "H", deck: null }), /could not be read/);
  assert.equal(variationIdOf(frontMatterWithVariation("", { id: "v", headline: "H", deck: "D" })), "v");
});

test("the body is the variation's own when it has one, and the change reason names the variation and its point", () => {
  assert.equal(bodyWithVariation("Current", { bodyMarkus: "Variation body" }), "Variation body");
  assert.equal(bodyWithVariation("Current", { bodyMarkus: null }), "Current");
  assert.equal(changeReasonFor({ variationNumber: 2, point: "A point." }), "Accepted variation 2: A point.");
  assert.ok(changeReasonFor({ variationNumber: 1, point: "x".repeat(400) }).length <= 240);
});
