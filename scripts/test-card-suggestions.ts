import assert from "node:assert/strict";
import test from "node:test";
import { createSuggestionLoader, openSuggestions } from "../lib/card-suggestions";
import type { RelatedEntry, RelatedItem } from "../lib/reference-links";

const item = (kind: "concept" | "reference", id: string): RelatedItem => ({ kind, lineageId: id, title: id, hashtag: kind === "concept" ? `#${id}` : null, nodeKey: null, nodeKind: null, host: null, sourceUri: null, sourcePublishedAt: null, addedAt: null });
const entry = (id: string, kind: "concept" | "reference", state: "suggested" | "current", similarity: number | null): RelatedEntry => ({ relationId: id, state, provenance: "suggested", predicate: "related_to", direction: "outgoing", item: item(kind, id), similarity, label: null });

test("a card shows the two most likely suggestions of each kind, open ones only", () => {
  const shown = openSuggestions([
    entry("c1", "concept", "suggested", 0.5), entry("c2", "concept", "suggested", 0.9), entry("c3", "concept", "suggested", 0.7), entry("c4", "concept", "current", 0.99),
    entry("r1", "reference", "suggested", null), entry("r2", "reference", "suggested", 0.6),
  ]);
  assert.deepEqual(shown.concepts.map((row) => row.relationId), ["c2", "c3"]);
  assert.deepEqual(shown.references.map((row) => row.relationId), ["r2", "r1"], "a row with no close match comes last, never first");
});

test("the loader reads at most two References at once, shares a read, and tries a failed one again", async () => {
  let running = 0, peak = 0, reads = 0, fail = true;
  const loader = createSuggestionLoader({
    listForReference: async (lineage) => {
      reads += 1; running += 1; peak = Math.max(peak, running);
      await new Promise((resolve) => setTimeout(resolve, 10));
      running -= 1;
      if (lineage === "bad" && fail) throw new Error("no");
      return [];
    },
  });
  await Promise.all(["a", "b", "c", "d", "e", "a"].map((lineage) => loader.load(lineage)));
  assert.equal(reads, 5, "the second ask for a is the shared read");
  assert.ok(peak <= 2, `at most two at once, saw ${peak}`);
  await assert.rejects(loader.load("bad"));
  fail = false;
  assert.deepEqual(await loader.load("bad"), []);
});
