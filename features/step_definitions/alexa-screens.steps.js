const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-screens.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-screens.ts", name], {
      cwd: path.resolve(__dirname, "../.."),
      maxBuffer: 8 * 1024 * 1024,
    });
    passed.push(JSON.parse(result.stdout.trim().split("\n").pop()).behaviour);
  }
  return passed;
}

function step(keyword, text, ...names) {
  keyword(text, { timeout: 120_000 }, async function () {
    this.passed = [...(this.passed ?? []), ...(await behaviours(...names))];
  });
}

function pass(text) {
  Then(text, function () {
    assert.ok(this.passed && this.passed.length > 0);
  });
}

const FEED = "the headlines show the feed on a screen";

step(Given, "a listener on an Echo Show", FEED);
step(When, "they open the skill", FEED);
pass("the headlines are read aloud");
pass("the feed of those stories appears under the publication's name, with each story's deck and byline");

step(Given, "a listener on an Echo Show has heard the headlines", FEED);
step(When, "they ask for the second one", "a story shows its own screen while it is read");
pass("that story is read aloud");
step(Then, "its screen shows the title, byline and the body as plain paragraphs", "the story screen shows the body as plain paragraphs");

step(Given, "a listener on an Echo Show has the feed on screen", FEED);
step(When, "they touch the third card", "touching a card reads that story and shows it");
pass("the third story is read aloud and its screen appears");

step(When, "a touch names a story past the end of the list", "touching a card past the list shows the headlines again");
pass("the headlines are read again and the feed appears");

step(Given, "a listener on a speaker without a screen", "a voice-only device gets speech and no screen");
step(When, "they open the skill and ask for a story", "a voice-only device gets speech and no screen");
pass("they hear the same speech and no screen is sent");
