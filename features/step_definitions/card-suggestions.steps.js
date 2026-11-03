const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-card-suggestions-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of ["a feed whose first Reference has three suggested concepts and three suggested References", "a feed of forty References"]) Given(given, function () {});
for (const when of [
  "the first card is on screen",
  "the editor accepts a suggested concept and rejects a suggested Reference on the card",
  "the editor types a hashtag in the box on a card and taps Create and tag",
  "the feed has loaded",
  "the editor opens the page on a phone",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-card-suggestions-ui.ts (a real browser, fixture data).
const outcomes = {
  "it shows two concepts and two References, most likely first, and a card with none shows nothing": "the_most_likely_suggestions",
  "each decision is recorded with the Related section's call and the Reference itself is not voted on": "one_tap_decides",
  "the Reference is tagged through the Related section's own action": "the_hashtag_box",
  "only the visible cards read their suggestions and none is read twice": "only_what_is_on_screen_is_read",
  "Accept and Reject are at least forty pixels tall, nothing scrolls sideways and the icons are Lucide": "phone",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 120000 }, async function () { await browser(scenario); });
