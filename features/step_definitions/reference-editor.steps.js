const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

Given("an isolated inbox of synthetic pending references", function () {
  this.referenceEditorResult = null;
});

const behaviors = [
  ["selection", "the editor selects a pending reference on desktop and mobile", "its review card says there is no prediction, and offers Accept and Reject"],
  ["feedback", "the editor accepts, adds a Why note, and later rejects by choosing a reason chip", "the answers, the reason and the Why note survive a fresh page load"],
  ["recovery", "the editor double taps Accept and the save fails before a retry succeeds", "only one request is sent per attempt and the failed attempt says so in words and keeps the Why note"],
  ["revision_from_message", "the editor reloads a rejected reference and clears its saved explanation", "the reason from review history remains selected and the cleared explanation survives another reload"],
  ["predictions", "the editor opens a reference with publication and Section predictions", "the predicted side is marked and the bar carries its confidence, and never invents one"],
  ["prediction_failure", "the editor retries a failed prediction read", "the error is distinct from an absent prediction"],
  ["prediction_loading", "the editor opens a reference while predictions are loading", "the control says it is reading the prediction and stays usable"],
  ["readonly", "a person without editing permission selects a reference", "the card says in words that editor access is required and no tap sends a request"],
  ["queue", "the editor works through the pending queue at 375 and 1440 pixels", "a bottom bar shows Previous, the position and Next with one URL per item"],
  ["card_layout", "the editor opens a reference at 375 and 1440 pixels", "the prediction bar sits above the buttons, and the buttons and the reason field span the card"],
  ["responsive_detail", "the editor opens a reference at 375, 768, 834, 1024 and 1440 pixels", "at 375, 768 and 834 the detail takes the feed's place at the full width with a Back control that returns to the feed"],
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
  ["revision_from_message", "a reason chip tapped while a Reject is still saving is saved right after it, without losing the typed explanation"],
  ["predictions", "accepting by tap or by the A key keeps the editor's chosen Section"],
  ["predictions", "the Cyclotron's matching or differing answer is marked with a check or cross as well as colour"],
  ["queue", "swiping left or right and the arrow keys move through the queue"],
  ["queue", "after the last item the page says All caught up"],
  ["card_layout", "every icon is a Lucide icon and nothing scrolls sideways"],
  ["responsive_detail", "at 1024 and 1440 the detail is a pane of 24 to 28rem to the right of the feed, with no Back control"],
  ["responsive_detail", "at every width nothing scrolls sideways and the detail is in the page, not a sheet over it"],
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

When("the editor opens the References page at four desktop sizes", { timeout: 300_000 }, async function () {
  if (!process.env.PAPYRUS_REFERENCES_FILL_URL) return "skipped";
  const result = await promisify(execFile)(process.execPath,
    ["--import", "tsx", "scripts/test-references-fill-viewport.ts"],
    { cwd: path.resolve(__dirname, "../.."), maxBuffer: 8 * 1024 * 1024 });
  this.referencesFillResult = result.stdout;
});
for (const step of [
  "the feed scroller and the Detail pane both end at the bottom of the viewport",
  "the confidence bar sits above the buttons on a card and in the Detail pane",
  "the space under a card's You buttons is no larger than the card's side padding",
]) {
  Then(step, function () {
    if (!process.env.PAPYRUS_REFERENCES_FILL_URL) return "skipped";
    assert.ok(this.referencesFillResult.includes("References fill-viewport passed at 1024x768"));
  });
}
