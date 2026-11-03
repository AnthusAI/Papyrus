import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ReferenceAttachmentRecord } from "../lib/category-repository";
import { captureStateOfAttachments, normalizeCaptureState } from "../lib/reference-capture";
import { matchesCaptured } from "../lib/reference-policy";

type Vector = { name: string; attachments: Array<Record<string, unknown>>; expected: string };
const file = JSON.parse(readFileSync(join(process.cwd(), "scripts/fixtures/capture-state-vectors.json"), "utf8")) as { vectors: Vector[] };

for (const vector of file.vectors) {
  const attachments = vector.attachments.map((row) => ({ referenceLineageId: "lineage", referenceId: "ref", ...row })) as unknown as ReferenceAttachmentRecord[];
  assert.equal(captureStateOfAttachments(attachments), vector.expected, vector.name);
}

// The stored value: empty or unknown reads as none, and only full is captured.
assert.equal(normalizeCaptureState(undefined), "none");
assert.equal(normalizeCaptureState(null), "none");
assert.equal(normalizeCaptureState(""), "none");
assert.equal(normalizeCaptureState("weird"), "none");
for (const state of ["full", "thin", "none", "running"]) assert.equal(normalizeCaptureState(state), state);
for (const [state, yes, no] of [["full", true, false], ["thin", false, true], ["none", false, true], ["running", false, true], ["", false, true], [null, false, true], [undefined, false, true]] as const) {
  assert.equal(matchesCaptured({ captureState: state }, "yes"), yes, `yes ${state}`);
  assert.equal(matchesCaptured({ captureState: state }, "no"), no, `no ${state}`);
  assert.equal(matchesCaptured({ captureState: state }, "any"), true, `any ${state}`);
}

console.log(`capture-state: ${file.vectors.length} vectors passed.`);
