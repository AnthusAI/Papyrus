const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-story-stars-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of ["the Stories board with rated and unrated Stories", "the Story editor open on a published Story"]) Given(given, function () {});

for (const when of [
  "the editor taps the third star on an unrated Story card and then taps it again",
  "the editor opens a rated Story and changes its rating in the drawer, and then changes it on the card",
  "the editor rates it one star",
  "the editor taps a star while the save fails",
  "the editor opens the board, a drawer and the editor on a phone",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-story-stars-ui.ts (a real browser, local preview data).
const outcomes = {
  "the card shows three solid stars and two outline stars, with the count written beside them": "card_tap",
  "the second tap clears the rating": "card_tap",
  "tapping a star did not open the Story": "card_tap",
  "the card follows the drawer and the drawer follows the card": "drawer_follows_card",
  "only ratings were saved, with no draft saved, no stage move and no publication": "drawer_follows_card",
  "the rating is saved by one plain update and the Story is still published with nothing unsaved": "editor_and_published",
  "the card says the rating could not be saved and shows the saved rating": "failed_save",
  "the five stars are at least forty pixels square, in one row, with Lucide icons and nothing scrolling sideways": "phone",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 180000 }, async function () { await browser(scenario); });
