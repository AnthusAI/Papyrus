const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-apl.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-apl.ts", name], {
      cwd: path.resolve(__dirname, "../.."),
      maxBuffer: 8 * 1024 * 1024,
    });
    passed.push(JSON.parse(result.stdout.trim().split("\n").pop()).behaviour);
  }
  return passed;
}

function step(text, ...names) {
  When(text, { timeout: 120_000 }, async function () {
    this.passed = [...(this.passed ?? []), ...(await behaviours(...names))];
  });
}

function pass(text) {
  Then(text, function () {
    assert.ok(this.passed && this.passed.length > 0);
  });
}

const device = "an APL device gets a directive and a voice-only device gets none";
step("a request arrives from a device that supports APL", device);
pass("the skill can show a document");
pass("a request from a voice-only device gets no directive");

step("the feed is rendered for a list of stories", "the feed directive carries the stories as a datasource");
pass("each story keeps its position in the feed");
pass("a story with an image has an image address and a story without one has none");
pass("the headline and deck are in the datasource with the site theme");

step("a story is rendered for the screen", "the story directive carries the title, byline, date and body");
pass("the datasource has the title, the byline with the date and the body paragraphs");
pass("the hero image is left out when the story has none");

step("a person touches the third card of the feed", "a touched card opens the story at its index");
pass("the touch handler opens the story at index two");
pass("a touch it cannot read opens nothing");

step("the feed and story documents are inspected", "each document is valid APL laid out for every viewport profile");
pass("each is an APL document of version 2023.3 or newer");
pass("each has sizes for the round hub, the three landscape hubs and the TV");
pass("neither uses borders or dividers");
pass("the text sizes are readable");

step("a site sets no theme", "the theme comes from the site config with a brand fallback");
pass("the documents use the Pilobolus dark brand colours");
pass("a site theme is validated for colour format and text contrast");

step("the preview fixtures are rendered", "preview fixtures exist for every document and profile");
pass("there is one fixture per document and viewport profile for the APL authoring tool");
