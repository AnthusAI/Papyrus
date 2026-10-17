/**
 * Exercises `projectBodyIr` (lib/markus-body.ts) against bodyIr envelopes
 * produced by `papyrus ops content markus-derive --emit-ir` from the PPY-e169c5
 * fixtures (scripts/fixtures/body-ir/). Run with:
 *
 *   npx tsx scripts/test-markus-body.ts
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BodyIrError, matchBodyImages, projectBodyIr } from "../lib/markus-body";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

function assertEqual<T>(actual: T, expected: T, message: string) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  assert(a === e, `${message}\n  expected: ${e}\n  actual:   ${a}`);
}

function loadEnvelope(name: string): Record<string, any> {
  return JSON.parse(readFileSync(path.join(__dirname, "fixtures", "body-ir", `${name}.json`), "utf8"));
}

function assertThrowsBodyIrError(run: () => unknown, message: string) {
  try {
    run();
  } catch (error) {
    assert(error instanceof BodyIrError, `${message}: threw ${String(error)} instead of BodyIrError`);
    return;
  }
  throw new Error(`FAIL: ${message}: did not throw`);
}

const plain = projectBodyIr(loadEnvelope("plain"));
assertEqual(plain.body, ["First paragraph here.", "Second paragraph wraps a line."], "plain body");
assertEqual(plain.pullQuotes, [], "plain has no pull quotes");
assertEqual(plain.imageSrcs, [], "plain has no images");

const imageAndCitation = projectBodyIr(JSON.stringify(loadEnvelope("image-and-citation")));
assertEqual(
  imageAndCitation.body,
  [
    "Intro with a cite [1] and again [1].",
    "Later a pair [2][1].",
    "1. Source A. (2024, January 2). https://example.com/a",
    "2. Source B. (2023, May 6). https://example.com/b",
  ],
  "citations numbered by first appearance, bibliography appended, image paragraph removed",
);
assertEqual(imageAndCitation.imageSrcs, [{ src: "images/a.png", alt: "A", layout: "full" }], "image token resolves");

const pullQuote = projectBodyIr(loadEnvelope("pull-quote"));
assertEqual(pullQuote.body, ["Before.", "After."], "pull-quote body");
assertEqual(pullQuote.pullQuotes, ["A quoted line."], "pull-quote extracted");

for (const name of ["plain", "image-and-citation", "pull-quote"]) {
  const projection = projectBodyIr(loadEnvelope(name));
  assert(!/PAPYRUSMARKUP/.test(JSON.stringify(projection)), `${name}: placeholder token leaked into the projection`);
}

const wrongEnvelopeVersion = loadEnvelope("plain");
wrongEnvelopeVersion.schemaVersion = 2;
assertThrowsBodyIrError(() => projectBodyIr(wrongEnvelopeVersion), "wrong envelope schemaVersion");

const wrongIrVersion = loadEnvelope("plain");
wrongIrVersion.markus.irSchemaVersion = 2;
assertThrowsBodyIrError(() => projectBodyIr(wrongIrVersion), "wrong markus.irSchemaVersion");

const wrongDocumentVersion = loadEnvelope("plain");
wrongDocumentVersion.document.schema_version = 2;
assertThrowsBodyIrError(() => projectBodyIr(wrongDocumentVersion), "wrong document schema_version");

const unresolvedToken = loadEnvelope("image-and-citation");
unresolvedToken.papyrus.citations = {};
assertThrowsBodyIrError(() => projectBodyIr(unresolvedToken), "unresolved token never leaks");

assertThrowsBodyIrError(() => projectBodyIr("not json"), "invalid JSON string");
assertThrowsBodyIrError(() => projectBodyIr(null), "null bodyIr");

const bodyImages = [
  { src: "images/a.png", alt: "A" },
  { src: "https://cdn.example.com/b.jpg", alt: "B", credit: "Photo" },
];
assertEqual(
  matchBodyImages(bodyImages, [null, "images/a.png"]),
  [
    { kind: "media", mediaIndex: 1 },
    { kind: "external", image: bodyImages[1] },
  ],
  "images match media by srcPath or stay external",
);
assertThrowsBodyIrError(() => matchBodyImages([{ src: "images/missing.png", alt: "" }], ["images/a.png"]), "unmatched relative image");

console.log("markus-body: all assertions passed");
