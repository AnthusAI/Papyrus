const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

Given("an isolated newsroom with synthetic stories", function () {
  this.uxReviewResult = null;
});

const behaviors = [
  ["proposed_stories", "the editor looks for the stories AI has proposed",
    ["the sidebar, the Needs me filter, the counts and the kind label all say Proposed Stories", "no editor-facing line calls a proposed story a draft"]],
  ["board_order", "the editor opens the Stories board at 1440 and 375 pixels",
    ["each column lists its stories from the most recently updated to the oldest", "a story with no date sits at the bottom of its column",
      "without that rule a column is ordered by id, which is the order the editor saw before"]],
  ["board_stage_columns", "the editor opens the Stories board",
    ["the first column is Idea, ahead of Reporting", "each Idea card is marked Generated or Started by a person", "a story at the assignment stage is not on the Stories board"]],
  ["detail_stable", "the editor opens a story at 1440, 834 and 375 pixels and every animation frame is recorded",
    ["the detail view's background is opaque and not fading from its very first frame", "the detail view stays in one place at one size while the story loads",
      "the loading shape is the loaded editor's size, so nothing below it moves when the story arrives"]],
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
