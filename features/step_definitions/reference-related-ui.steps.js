const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = async (name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-related-links.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

for (const given of [
  "a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference",
  "a site with no knowledge index and a Reference with one confirmed concept",
  "a concept page with two References linked by editors",
]) Given(given, function () { this.relatedResult = ""; });

for (const when of [
  "the editor opens the Related section",
  "the editor accepts the suggested concept",
  "the editor writes a reason and rejects the suggested Reference",
  "the editor types a hash and the start of a concept name and presses the match",
  "the editor pastes a link and then types words of a title",
  "the editor presses Suggest more and then adds a concept by its exact hashtag",
  "the editor opens the concept page",
  "the editor looks at the Related section at 375 and 1440 pixels",
]) When(when, function () { this.relatedResult = ""; });

// Each outcome runs the named browser scenario in scripts/test-related-links.ts (every one covers 375 and 1440 pixels).
const outcomes = [
  ["marks", [
    "the confirmed concept is a chip with a hash icon and its hashtag",
    "a suggested link says \"Suggested\" with a sparkles icon, its close match as text, and likely or possible when known",
    "a Reference card shows the title, the host and the relation in words",
  ]],
  ["dates", [
    "every Reference card says when it was published and when it was added",
    "a Reference with no publication date says \"published unknown\"",
  ]],
  ["accept", [
    "the decision is saved with the accept choice",
    "the concept becomes a plain chip without the word \"Suggested\"",
  ]],
  ["reject", [
    "the reason box is offered beside the Accept and Reject buttons",
    "the decision is saved with the reject choice and the reason",
    "the suggestion leaves the list",
  ]],
  ["addConcept", [
    "the matches are full-width buttons under the box",
    "a human link to that concept is written and the box clears",
    "the concept shows as a chip",
  ]],
  ["addReference", [
    "each match shows its title, host and both dates as a full-width button",
    "pressing one writes a human link to that Reference",
  ]],
  ["noIndex", [
    "the section says \"Suggestions need the knowledge index\"",
    "the confirmed concept is still listed and the typed hashtag is linked",
  ]],
  ["concept", [
    "\"Linked by editors\" lists both References with both dates",
    "pasting a link in the box there links another Reference to the concept",
  ]],
  ["design", [
    "there are no borders or outlines and no drop-downs",
    "nothing scrolls sideways",
  ]],
];
for (const [scenario, thens] of outcomes) {
  for (const then of thens) Then(then, async function () { assert.ok((await browser(scenario)).includes(`passed: ${scenario}`)); });
}
