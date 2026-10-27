const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

Given("an isolated inbox of synthetic pending references", function () {
  this.referenceEditorResult = null;
});

const behaviors = [
  ["selection", "the editor selects a pending reference on desktop and mobile", "its review card has a Cyclotron row that says there is no prediction and a You row with Accept and Reject"],
  ["feedback", "the editor accepts, adds a Why note, and later rejects by choosing a reason chip", "the answers, the reason and the Why note survive a fresh page load"],
  ["recovery", "the editor double taps Accept and the save fails before a retry succeeds", "only one request is sent per attempt and the failed attempt says so in words and keeps the Why note"],
  ["revision_from_message", "the editor reloads a rejected reference and clears its saved explanation", "the reason from review history remains selected and the cleared explanation survives another reload"],
  ["predictions", "the editor opens a reference with publication and Section predictions", "the Cyclotron row highlights its Accept or Reject with its confidence and never invents one"],
  ["prediction_failure", "the editor retries a failed prediction read", "the error is distinct from an absent prediction"],
  ["prediction_loading", "the editor opens a reference while predictions are loading", "the Cyclotron row says Loading and the controls stay usable"],
  ["readonly", "a person without editing permission selects a reference", "the card says in words that editor access is required and no tap sends a request"],
  ["queue", "the editor works through the pending queue at 375 and 1440 pixels", "a bottom bar shows Previous, the position and Next with one URL per item"],
  ["card_layout", "the editor opens a reference at 375 and 1440 pixels", "the Cyclotron row sits above the You row and the Why box spans the card"],
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
  ["feedback", "tapping the selected answer again never unselects it or sends another write"],
  ["revision_from_message", "live feedback updates refresh an untouched card while preserving an unsaved draft"],
  ["predictions", "accepting by tap or by the A key keeps the editor's chosen Section"],
  ["predictions", "the Cyclotron's matching or differing answer is marked with a check or cross as well as colour"],
  ["queue", "swiping left or right and the arrow keys move through the queue"],
  ["queue", "after the last item the page says All caught up"],
  ["card_layout", "every icon is a Lucide icon and nothing scrolls sideways"],
  ["predictions", "the human answer is final and replaces the Cyclotron's"],
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
