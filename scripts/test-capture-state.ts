import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ReferenceAttachmentRecord } from "../lib/category-repository";
import { captureReasonWords, captureStateOfAttachments, captureStatus, normalizeCaptureState } from "../lib/reference-capture";
import { matchesCaptured } from "../lib/reference-policy";

type Vector = { name: string; attachments: Array<Record<string, unknown>>; expected: string };
const file = JSON.parse(readFileSync(join(process.cwd(), "scripts/fixtures/capture-state-vectors.json"), "utf8")) as { vectors: Vector[] };

for (const vector of file.vectors) {
  const attachments = vector.attachments.map((row) => ({ referenceLineageId: "lineage", referenceId: "ref", ...row })) as unknown as ReferenceAttachmentRecord[];
  assert.equal(captureStateOfAttachments(attachments), vector.expected, vector.name);
}

// A video captured from its page alone: thin however long, with the reason shown in words (To capture lists it with that reason).
const videoCard = (textReason: string, edited = false): ReferenceAttachmentRecord[] => [{
  id: "card", role: "curation", sortKey: "003-curation", referenceLineageId: "lineage", referenceId: "ref",
  metadata: { kind: "reference-curation", status: "degraded", capture: { status: "completed", wordCount: 900, textVia: "youtube_description", textReason, textSortKey: "curation-text" }, signals: { wordCount: 900 }, labels: [], current: { textSortKey: edited ? "curation-edit-0001-text" : "curation-text" } },
}] as unknown as ReferenceAttachmentRecord[];
for (const reason of ["awaiting_transcript", "no_transcript", "unavailable", "unsupported_platform"]) {
  const status = captureStatus(videoCard(reason));
  assert.equal(status.state, "thin", reason);
  assert.equal(status.reason, reason, reason);
  assert.ok(captureReasonWords(reason) && !captureReasonWords(reason)!.startsWith("Capture failed"), `${reason} has words`);
}
assert.match(captureReasonWords("no_transcript") ?? "", /no transcript/);
assert.equal(captureStatus(videoCard("awaiting_transcript", true)).state, "full", "the transcript a person or the worker saved makes it full");
assert.equal(captureStatus(videoCard("awaiting_transcript", true)).reason, null);

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
