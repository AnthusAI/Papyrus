const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

Given("an isolated newsroom with synthetic stories", function () {
  this.uxReviewResult = null;
});

const behaviors = [
  ["ideas_wording", "the editor looks for the story ideas AI has generated",
    ["the Needs me filter, the counts and the card all say ideas, and the sidebar and the Stories board have no Proposed Stories page, link or count", "no editor-facing line calls an idea a Proposed Story or a draft"]],
  ["board_order", "the editor opens the Stories board at 1440 and 375 pixels",
    ["each column lists its stories from the most recently updated to the oldest", "a story with no date sits at the bottom of its column",
      "without that rule a column is ordered by id, which is the order the editor saw before"]],
  ["board_stage_columns", "the editor opens the Stories board",
    ["the first column is Idea, ahead of Reporting", "each Idea card is marked Generated or Started by a person", "a story at the assignment stage is not on the Stories board"]],
  ["detail_stable", "the editor opens a story at 1440, 834 and 375 pixels and every animation frame is recorded",
    ["the detail view's background is opaque and not fading from its very first frame", "the detail view stays in one place at one size while the story loads",
      "the loading shape is the loaded editor's size, so nothing below it moves when the story arrives"]],
  ["board_stacked_on_phones", "the editor opens the Stories board at 375 and 390 pixels wide, and at 667 by 375, 834 and 1440",
    ["below 600 pixels the stages are sections of one vertical list with no horizontal scroll and exactly one vertical scroller",
      "at 600 pixels and wider, including a phone in landscape and a tablet, the stages stay side by side columns"]],
  ["board_pages_on_phones", "the editor scrolls a stage with far more stories than one page on a 375 pixel wide board",
    ["only a bounded number of cards is in the page at once", "the next page is requested through the board's near-the-end callback and the stage grows",
      "the first page of a short stage requests no more than once"]],
  ["board_phone_detail_and_collapse", "the editor scrolls the stacked board, opens a story, closes it, and reloads after collapsing a section",
    ["the detail view covers the board and the same story is focused again at the same scroll position", "the collapsed section is still collapsed after the reload"]],
  ["board_skeleton_agrees", "the editor loads the Stories board at 375, 599, 600 and 640 pixels",
    ["the loading skeleton is one stacked column below 600 pixels and three columns from 600 pixels", "the skeleton changes shape at the same width as the board changes layout"]],
  ["board_phone_header", "the editor opens the Stories, Assignments and section boards at 375 and 390 pixels wide, and at 667 by 375, 834 and 1440",
    ["below 600 pixels every header control is inside the screen, not clipped, at least 44 pixels tall, and search is at least 120 pixels wide", "from 600 pixels the header keeps its size"]],
];

for (const [name, action, outcomes] of behaviors) {
  When(action, { timeout: 180_000 }, async function () {
    const result = await promisify(execFile)(process.execPath,
      ["--import", "tsx", "scripts/test-newsroom-ux-review.ts", name],
      { cwd: path.resolve(__dirname, "../.."), maxBuffer: 8 * 1024 * 1024 });
    this.uxReviewResult = result.stdout;
  });
  for (const outcome of outcomes) {
    Then(outcome, function () {
      assert.ok(this.uxReviewResult.includes(`Newsroom UX review scenario passed: ${name}`));
    });
  }
}
