const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-story-stars-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of ["the Stories board with rated and unrated Stories", "the Story editor open on a published Story"]) Given(given, function () {});

for (const when of [
  "the editor looks at a rated card and an unrated card",
  "the editor opens an unrated Story and taps the third star, and then taps it again",
  "the editor rates it one star",
  "the editor taps a star in the drawer while the save fails",
  "the editor opens the board, a drawer and the editor on a phone",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-story-stars-ui.ts (a real browser, local preview data).
const outcomes = {
  "the rated card shows one solid star and the number in its top row, with no row of its own and no controls": "card_mark",
  "the unrated card shows no rating": "card_mark",
  "tapping the rating on a card opens the Story": "card_mark",
  "the drawer shows three solid stars and two outline stars, with the count written beside them, and the card shows the number three": "drawer_tap",
  "the second tap clears the rating and the card shows no rating": "drawer_tap",
  "only ratings were saved, with no draft saved, no stage move and no publication": "drawer_tap",
  "the rating is saved by one plain update and the Story is still published with nothing unsaved": "editor_and_published",
  "the drawer says the rating could not be saved and the drawer and the card show the saved rating": "failed_save",
  "the five stars in the drawer and the editor are at least forty pixels square, in one row, with Lucide icons and nothing scrolling sideways": "phone",
  "the card's rating stays in its top row": "phone",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 180000 }, async function () { await browser(scenario); });
