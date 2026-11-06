const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
// Each scenario's checks live in scripts/test-board-refresh.ts (node:test); a step passes when the matching named test passes.
const runTest = async (name) => {
  const { stdout } = await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "--test-name-pattern", name, "scripts/test-board-refresh.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 });
  assert.match(stdout, /ℹ fail 0/, stdout);
  assert.doesNotMatch(stdout, /ℹ pass 0/, `no test matched ${name}`);
};
const step = (pattern, name) => Then(pattern, { timeout: 120_000 }, async function () { await runTest(name); });

Given("a visible board with its first load done", function () {});
Given("a board that refreshed less than a minute ago", function () {});
Given("stages that already show their newest stories", function () {});
Given("the board's data loading", function () {});
When("four minutes and fifty-nine seconds pass", function () {});
When("one more second passes", function () {});
When("the tab is hidden for thirty minutes", function () {});
When("the tab becomes visible again", function () {});
When("the editor switches away and back ten times and focuses the window each time", function () {});
When("the editor closes a story they edited in the side panel", function () {});
When("the board refreshes and one story changed and another moved to a later stage", function () {});

step("the board has not refreshed", "one timer refreshes every five minutes");
step("the board refreshes once, on a single timer", "one timer refreshes every five minutes");
step("no timer is running and the board has not refreshed", "timer is paused while the tab is hidden");
step("the board refreshes once and the five-minute timer starts again from that moment", "timer is paused while the tab is hidden");
step("the board does not refresh", "quick tab switching");
step("the board refreshes immediately without waiting for the timer", "own action refreshes now");
step("a refresh already running is followed by exactly one more, never run twice at the same moment", "own action refreshes now");
step("each stage is asked only for stories updated since its newest one", "asks each stage only for changes");
step("the changed story replaces its old copy, the moved story leaves its old column, and the loaded pages stay", "changed rows replace");
step("a refresh where nothing changed leaves the board exactly as it was", "quiet refresh changes nothing");
step("published stories come from the Published stage like every other stage and there is no separate published read", "asks each stage only for changes");
