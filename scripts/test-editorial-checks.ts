import assert from "node:assert/strict";
import {
  applyReplacement,
  editorialChecksEnabled,
  feedbackFor,
  groupByPolicy,
  inlineFindings,
  laneNotice,
  publishWarnings,
  UNSAVED_ITEM_ID,
  visibleFindings,
  type EditorialCheckResult,
  type EditorialFinding,
} from "../lib/editorial-checks";

function finding(overrides: Partial<EditorialFinding>): EditorialFinding {
  return {
    id: "f-0000000000000001",
    policyId: "no-hype",
    policyVersion: 1,
    detectorId: "hype",
    lane: "rules",
    severity: "warn",
    status: "violation",
    segmentId: "s-1",
    span: { start: 0, end: 4 },
    excerpt: "Huge",
    message: "No hype.",
    ...overrides,
  };
}

const body = "Huge wins 🚀 ahead. Calm text.";
const result: EditorialCheckResult = {
  schemaVersion: 1,
  offsetUnit: "utf16",
  document: { hash: "sha256:x", length: body.length },
  pack: { packId: "papyrus", version: "1" },
  segments: [
    { id: "doc", kind: "document", start: 0, end: body.length, textHash: "a" },
    { id: "s-1", kind: "sentence", block: "paragraph", parentId: "p-1", start: 0, end: 19, textHash: "b" },
  ],
  protected: [],
  findings: [],
  coverage: [],
  lanes: { rules: { status: "ran", detectors: 1 }, classifier: { status: "partial", reason: "3 segment(s) skipped: 20s deadline reached" } },
};

// Limatus spans are UTF-16, the same unit as JavaScript strings: the emoji counts as two.
assert.equal(body.slice(0, 19), "Huge wins 🚀 ahead.");

assert.equal(editorialChecksEnabled({ custom: { papyrusPlugins: { "editorial-checks": { contract: 1 } } } }), true);
assert.equal(editorialChecksEnabled({ custom: { papyrusPlugins: { signup: { contract: 1 } } } }), false);
assert.equal(editorialChecksEnabled(null), false);

const info = finding({ id: "f-info", severity: "info", span: { start: 20, end: 24 }, excerpt: "Calm" });
const error = finding({ id: "f-error", severity: "error", policyId: "evidence", span: { start: 5, end: 9 }, excerpt: "wins" });
const warn = finding({ id: "f-warn" });
const whole = finding({ id: "f-doc", segmentId: "doc", excerpt: "", span: { start: 0, end: body.length } });
assert.deepEqual(visibleFindings([info, warn, error], new Set()).map((f) => f.id), ["f-error", "f-warn", "f-info"]);
assert.deepEqual(visibleFindings([info, warn, error], new Set(["f-warn"])).map((f) => f.id), ["f-error", "f-info"]);
assert.deepEqual(inlineFindings([warn, whole]).map((f) => f.id), ["f-warn"]);
assert.deepEqual(groupByPolicy([info, warn, error]).map((g) => [g.policyId, g.severity, g.findings.length]), [["evidence", "error", 1], ["no-hype", "warn", 2]]);
assert.deepEqual(publishWarnings([info, warn, error, finding({ id: "f-review", status: "review" })], new Set(["f-error"])).map((f) => f.id), ["f-warn"]);

assert.equal(applyReplacement(body, { start: 0, end: 4 }, "Huge", "Some"), "Some wins 🚀 ahead. Calm text.");
assert.equal(applyReplacement(body, { start: 0, end: 4 }, "Tiny", "Some"), null, "a stale span is not applied");

const classifierFinding = finding({ id: "f-cls", lane: "classifier", probability: 0.6, rawProbability: 0.95 });
assert.deepEqual(feedbackFor(result, body, classifierFinding, "dismissed", null, "  house style allows it "), {
  itemId: UNSAVED_ITEM_ID,
  findingId: "f-cls",
  policyId: "no-hype",
  detectorId: "hype",
  lane: "classifier",
  probability: 0.95,
  decision: "dismissed",
  reason: "house style allows it",
  text: "Huge wins 🚀 ahead.",
});
assert.equal(feedbackFor(result, body, warn, "fixed", "item-1").text, null, "rule findings carry no example text");
assert.match(laneNotice(result) ?? "", /not judged: 3 segment/);

// --- findings on the rendered preview -------------------------------------------
import("../lib/editorial-preview").then(({ inlineLeaves, locate, planPreview, proseBlocks, selectionToSource, splitByMarks }) => {
  const token = "PAPYRUSMARKUP00001END";
  const paragraph = {
    type: "paragraph" as const,
    line: 3,
    inline: [
      { type: "text" as const, text: "Our layer is " },
      { type: "strong" as const, children: [{ type: "text" as const, text: "game-changing" }] },
      { type: "text" as const, text: ` for [teams] ${token}.` },
      { type: "soft_break" as const },
      { type: "code_span" as const, code: "x.y()" },
      { type: "text" as const, text: " ships." },
    ],
  };
  const heading = { type: "heading" as const, level: 1, line: 1, inline: [{ type: "text" as const, text: "Launch" }] };
  const document = { type: "document" as const, children: [heading, { type: "list" as const, ordered: false, start: null, line: 5, items: [{ type: "list_item" as const, checked: null, line: 5, children: [paragraph] }] }] };

  // Citation tokens take no width; breaks take one; code counts its text.
  assert.equal(inlineLeaves(paragraph.inline).text, "Our layer is game-changing for [teams] . x.y() ships.");
  assert.deepEqual(proseBlocks(document as never).map((block) => block.type), ["heading", "paragraph"]);

  // Whitespace never decides a match; the occurrence nearest the expected position wins.
  assert.deepEqual(locate("a b  a b", "a b", 0.9), { start: 5, end: 8 });
  assert.deepEqual(locate("Our layer is game-changing", "game-changing"), { start: 13, end: 26 });
  assert.equal(locate("nothing here", "absent"), null);

  const markupBody = "# Launch\n\n- Our layer is **game-changing** for [teams] [@cite].\n  `x.y()` ships.";
  const pStart = markupBody.indexOf("Our layer");
  const sTwo = markupBody.indexOf("`x.y()`");
  const plan = planPreview(
    document as never,
    {
      ...result,
      segments: [
        { id: "doc", kind: "document", start: 0, end: markupBody.length, textHash: "d" },
        { id: "p-1", kind: "paragraph", block: "listItem", start: pStart, end: markupBody.length, textHash: "p", text: "Our layer is game-changing for [teams]. x.y() ships." },
        { id: "s-1", kind: "sentence", block: "listItem", parentId: "p-1", start: pStart, end: sTwo - 3, textHash: "s1", text: "Our layer is game-changing for [teams]." },
        { id: "s-2", kind: "sentence", block: "listItem", parentId: "p-1", start: sTwo, end: markupBody.length, textHash: "s2", text: "x.y() ships." },
      ],
    },
    [
      finding({ id: "f-a", segmentId: "s-1", span: { start: pStart + 15, end: pStart + 28 }, excerpt: "game-changing", excerptText: "game-changing", severity: "warn" }),
      finding({ id: "f-b", segmentId: "s-1", span: { start: pStart, end: pStart + 28 }, excerpt: "Our layer is **game-changing", excerptText: "Our layer is game-changing", severity: "error", status: "review" }),
    ],
  );
  const annotation = plan.get(paragraph);
  assert.ok(annotation, "the list item's paragraph is matched despite emphasis, citations and the break");
  assert.deepEqual(
    annotation.marks.map((mark) => [mark.start, mark.end, mark.findingIds.join(","), mark.severity, mark.status]),
    [[0, 13, "f-b", "error", "review"], [13, 26, "f-a,f-b", "error", "violation"]],
  );
  assert.equal(plan.get(heading), undefined, "a block without a matching paragraph has no annotation");

  // A selection becomes the source span of the whole sentences it touches.
  assert.deepEqual(selectionToSource(annotation, { start: 2, end: 5 }), { start: pStart, end: sTwo - 3 });
  assert.deepEqual(selectionToSource(annotation, { start: 30, end: 48 }), { start: pStart, end: markupBody.length });
  assert.equal(selectionToSource(undefined, { start: 0, end: 1 }), null);

  assert.deepEqual(
    splitByMarks(10, 30, annotation.marks).map((piece) => [piece.start, piece.end, piece.mark?.findingIds.join(",") ?? null]),
    [[10, 13, "f-b"], [13, 26, "f-a,f-b"], [26, 30, null]],
  );
  console.log("editorial checks ok");
});
