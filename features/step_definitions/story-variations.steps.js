const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-story-variations-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of ["a Story with three variations", "a Story with three variations whose next version cannot be saved", "a Story with one variation"]) Given(given, function () {});

for (const when of [
  "the editor opens the variations",
  "the editor accepts the second variation and writes why",
  "the editor accepts the first variation and then the third",
  "the editor rejects the third variation and writes why",
  "the editor accepts the first variation",
  "the editor opens the variations on a phone",
  "the editor rejects the first variation",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-story-variations-ui.ts (a real browser, fixture data).
const outcomes = {
  "the three cards share a row in the order they were offered with the point first and connections that link to a Reference, a Story and a concept": "side_by_side",
  "the wording is saved as the next version first, and the variation is recorded as accepted by the editor with the reason": "accept_makes_the_next_version",
  "two versions were saved, the third variation is accepted and the first is on offer again and can be accepted again": "a_second_accept_puts_the_first_back_on_offer",
  "no version was saved and the reason stays readable on the card": "reject_with_a_reason",
  "the card shows the error and nothing is recorded as accepted": "a_failed_save_is_not_an_accept",
  "the single card says only one way to connect this was found and a Story with no variations shows nothing": "one_or_none",
  "the cards are in one column, nothing scrolls sideways and Accept and Reject are at least forty-four pixels tall": "phone",
  "Accept and Reject are words with Lucide icons, the state is a word with an icon, and there are no dropdowns, borders or outlines": "words_icons_and_flat_backgrounds",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 120000 }, async function () { await browser(scenario); });
