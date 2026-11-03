const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-reference-stars-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

Given("a References page with unrated, rated and automatically accepted References", function () {});

for (const when of [
  "the editor taps the fourth star on an unrated card and then taps it again",
  "the editor rates a card five stars and then accepts it, and accepts another card and then rates it three stars",
  "the editor includes the rated References",
  "the editor opens a rated Reference and changes its rating in the detail pane",
  "the editor taps a star while the save fails",
  "the editor opens the page on a phone",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-reference-stars-ui.ts (a real browser, fixture data).
const outcomes = {
  "the card shows four solid stars and one outline star, with the count written beside them": "tap_sets_and_clears",
  "the second tap clears the rating": "tap_sets_and_clears",
  "no vote was recorded by the rating alone and each vote leaves its stars as they were": "with_a_vote_in_either_order",
  "the saved ratings show on their cards and rating an automatic acceptance does not confirm it": "shows_what_is_saved",
  "the card and the list row follow the detail pane": "list_and_detail",
  "the card says the rating could not be saved and shows the saved rating": "a_failed_save_is_said",
  "the five stars are at least forty pixels square, in one row, with Lucide icons and nothing scrolling sideways": "phone",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 120000 }, async function () { await browser(scenario); });
