const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (script, name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", script, ...(name ? [name] : [])], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
const browser = (name) => run("scripts/test-reference-feed.ts", name);
const ranking = async () => (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-reference-feed-ranking.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

for (const given of [
  "a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction",
  "References whose accepted examples show how quickly the editor acts",
  "References older than three times the learned freshness",
  "References whose pictures load, fail, or were never found",
  "the References are still loading",
  "this browser saved the last feed it showed",
  "the feed is open",
]) Given(given, function () { this.feedResult = ""; });

// Each outcome runs the named browser scenario in scripts/test-reference-feed.ts (every one covers 375 and 1440 pixels).
const outcomes = [
  ["layout", [
    "the order runs from the strongest Accept, through the item with no prediction, to the strongest Reject",
    "the first card is the large lead card, and the grid has one column on a phone and three or more on a desktop",
    "every card shows its title, dek, source, age, the Cyclotron's Accept or Reject with its confidence and icon, and large Accept and Reject buttons",
    "nothing scrolls sideways and there are no drop-downs",
  ]],
  ["design", [
    "no card, tab, pill, chip, panel or skeleton has a border, an outline or a rule, and surfaces differ only by tone",
    "cards are rounded rectangles with a full-bleed picture across the top, and pills are fully rounded",
    "the feed has the sections Top predictions, More for you and Least likely in large type with no lines between them",
    "on a phone the first card's picture is on the first screen",
  ]],
  ["popover", [
    "it explains best bets first, confidence, fading toward not sure, Earlier and why a rated card stays put",
    "it says how many accepted examples have been learned from, or how many more are needed",
  ]],
  ["cached", [
    "the saved cards are shown at once with a note that they are the last view",
    "answering is switched off with the reason in words, and a saved copy never answers on its own",
  ]],
  ["lifecycle", [
    "each rated card stays in its place and shows Saved",
    "the Cyclotron's chip says Match with a check or Miss with a cross, in words and an icon as well as colour",
    "Rejecting asks for a reason in words and changes nothing until one is chosen",
    "the Rated tab lists the most recent answer first, and the next visit lists the answered cards there",
  ]],
];
When("the editor opens the feed at 375 and 1440 pixels", function () { this.feedResult = ""; });
When("the editor accepts a card, then rejects it with a reason, and rejects a card the Cyclotron expected to be rejected", function () { this.feedResult = ""; });
When("the editor opens how this feed is ranked", function () { this.feedResult = ""; });
When("the editor opens the References page while the session is still being confirmed", function () { this.feedResult = ""; });
for (const [name, texts] of outcomes) {
  for (const text of texts) {
    Then(text, { timeout: 240_000 }, async function () {
      assert.ok((await browser(name)).includes(`Reference feed scenario passed: ${name}`));
    });
  }
}

// "the editor opens the feed at 375 and 1440 pixels" opens every scenario that uses it; the outcomes below each run their own browser scenario.
When("the feed is ranked", { timeout: 60_000 }, async function () { this.feedResult = await ranking(); });
Then("an old prediction keeps only part of its distance from not sure and never falls below a fresh Reject", function () { assert.match(this.feedResult, /Age pulls a prediction toward uncertain/); });
Then("with fewer than ten accepted examples there is no fading and no Earlier section", function () { assert.match(this.feedResult, /Fewer than ten accepted examples means no decay/); });
Then("a card rated this visit does not move any other card", function () { assert.match(this.feedResult, /Rating one item does not move the others/); });
Then("they appear in an Earlier section after everything in the feed, and under the Earlier tab", async function () { assert.ok((await browser("earlier")).includes("passed: earlier")); });
Then("an Earlier card can be rated and stays where it is", async function () { assert.ok((await browser("earlier")).includes("passed: earlier")); });
Then("the pictures are lazy, in a fixed frame and requested with no referrer", async function () { assert.ok((await browser("images")).includes("passed: images")); });
Then("a missing or failing picture shows a soft gradient tile with the source's mark and name", async function () { assert.ok((await browser("images")).includes("passed: images")); });
Then("the page header, the tabs and card skeletons are on screen and no text says it is checking credentials", async function () { assert.ok((await browser("skeleton")).includes("passed: skeleton")); });
Then("the saved copy and the session summary expire, survive a blocked or full browser store, and are wiped on sign-out", async function () { assert.match(await ranking(), /The saved copy and the session display survive a return visit/); });
