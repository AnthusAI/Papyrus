const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
// Each scenario's checks live in scripts/test-board-head-index.ts (node:test, a fake index that counts rows read); a step passes when the named test passes.
const runTest = async (name) => {
  const { stdout } = await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "--test-name-pattern", name, "scripts/test-board-head-index.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 });
  assert.match(stdout, /ℹ fail 0/, stdout);
  assert.doesNotMatch(stdout, /ℹ pass 0/, `no test matched ${name}`);
};
const step = (pattern, name) => Then(pattern, { timeout: 120_000 }, async function () { await runTest(name); });

Given("a story that was written in Copywriting and then published in a later version", function () {});
When("the board loads its columns from the head stage index", function () {});
step("the story shows in Published only", "shows only in Published");
step("the Copywriting column read no row of that story", "shows only in Published");

Given("a board showing a story in Copywriting", function () {});
When("an editor saves a new version of that story in Illustration and the board refreshes", function () {});
step("the story shows once, in Illustration", "shows the story once, in its new stage");
step("no card of that story is left in Copywriting", "shows the story once, in its new stage");

Given("30 stories in Published, each published five times", function () {});
When("the board loads the Published column", function () {});
step("it reads 25 rows for its first page, one per story, in one request", "a column reads only the stories it shows");
step("the old stage index would have read every saved version to fill the same column", "a column reads only the stories it shows");

Given("a site whose brand does not set storyHeadStageIndex", function () {});
When("the board loads a column", function () {});
step("it reads the old stage index and still hides superseded versions", "has not switched keeps today's board");
step("a refresh replaces only the rows that changed, as before", "has not switched keeps today's board");

Given("a site that has switched but whose backend has no head stage index yet", function () {});
step("the column still shows its stories, read from the old stage index", "drops back to the stage index");
step("later columns and refreshes read the old stage index without asking for the missing one again", "drops back to the stage index");
step("any other error, such as a refused authorization, is shown and not taken for a missing index", "not mistaken for a missing index");
