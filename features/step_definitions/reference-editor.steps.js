const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

Given("an isolated inbox of synthetic pending references", function () {
  this.referenceEditorResult = null;
});

const behaviors = [
  ["selection", "the editor selects a pending reference on desktop and mobile", "its detail offers approval and rejection and says no prediction was recorded"],
  ["feedback", "the editor approves without an explanation, adds feedback, and later rejects with a reason", "approval, rejection, and revised optional explanations survive a fresh page load"],
  ["recovery", "the editor double clicks approval and the save fails before a retry succeeds", "only one request is sent per attempt and the failed attempt retains the pending status and explanation"],
  ["revision_from_message", "the editor reloads a rejected reference and clears its saved explanation", "the reason from review history remains selected and the cleared explanation survives another reload"],
  ["predictions", "the editor opens a reference with publication and Section predictions", "both prediction scopes are visible and missing confidence, version, and teaching counts are not invented"],
  ["prediction_failure", "the editor retries a failed prediction read", "the error is distinct from an absent prediction and approval stays available"],
  ["prediction_loading", "the editor opens a reference while predictions are loading", "loading is distinct from an absent prediction and approval stays available"],
  ["readonly", "a person without editing permission selects a reference", "its detail explains the permission requirement and neither review action can send a request"],
  ["empty", "the editor opens an inbox with no imported references", "the inbox explains the empty state without rendering reference rows"],
];

for (const [name, action, outcome] of behaviors) {
  When(action, { timeout: 120_000 }, async function () {
    const result = await promisify(execFile)(process.execPath,
      ["--import", "tsx", "scripts/test-reference-editor-review.ts", name],
      { cwd: path.resolve(__dirname, "../.."), maxBuffer: 8 * 1024 * 1024 });
    this.referenceEditorResult = result.stdout;
  });
  Then(outcome, function () {
    assert.ok(this.referenceEditorResult.includes(`Reference editor scenario passed: ${name}`));
  });
}

for (const [name, outcome] of [
  ["selection", "browser Back restores the previous reference and then clears the detail at the inbox"],
  ["selection", "changing status filters preserves the selected reference and its unsaved explanation"],
  ["feedback", "unchanged or just-saved feedback cannot create another completed write"],
  ["revision_from_message", "live feedback updates refresh an untouched form while preserving an unsaved draft"],
  ["predictions", "ordinary approval and agreeing with a prediction both keep the editor's chosen Section"],
  ["predictions", "revising accepted feedback retains the recorded Section until the editor explicitly removes it"],
  ["predictions", "a completed advanced review cannot be submitted again"],
]) {
  Then(outcome, function () {
    assert.ok(this.referenceEditorResult.includes(`Reference editor scenario passed: ${name}`));
  });
}

Given("an explicitly configured local reference demo", function () {
  if (!process.env.PAPYRUS_REFERENCE_LAYOUT_URL) return "skipped";
});
When("the editor opens the full newsroom at 1280 by 720", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath,
    ["--import", "tsx", "scripts/test-reference-editor-layout.ts"],
    { cwd: path.resolve(__dirname, "../.."), maxBuffer: 8 * 1024 * 1024 });
  this.referenceEditorLayoutResult = result.stdout;
});
Then("a reference row is visible inside the list viewport and pending feedback is reachable", function () {
  assert.ok(this.referenceEditorLayoutResult.includes("Reference editor layout passed at 1280x720"));
});
