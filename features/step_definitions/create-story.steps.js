const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-create-story-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

Given("a References page with a pending, a rejected and an accepted Reference", function () {});

for (const when of [
  "the editor taps Create Story on the pending card",
  "the editor taps Create Story on the rejected card",
  "the editor taps Create Story on the accepted card",
  "the editor taps Create Story twice on the same card and then taps Create another",
  "the editor taps \"As a post\" on a card",
  "the editor opens a pending Reference and taps Create Story in the detail pane",
  "the editor opens the page on a phone",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-create-story-ui.ts (a real browser, fixture data).
const outcomes = {
  "the Story opens in the article editor and the Reference is accepted with no reason": "one_tap_on_a_pending_reference",
  "the card says its vote stays and no vote is recorded": "a_rejected_reference_stays_rejected",
  "the Story opens and no vote is recorded": "an_accepted_reference",
  "the second tap offers the existing Story and only the deliberate choice makes a second one": "a_second_tap_offers_the_existing_story",
  "the Story opens with no dialog and only Lucide icons": "a_post_without_a_dialog",
  "the Story opens and the Reference is accepted with no reason": "the_detail_pane_has_it",
  "Create Story is at least forty pixels tall and nothing scrolls sideways": "phone",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 120000 }, async function () { await browser(scenario); });
