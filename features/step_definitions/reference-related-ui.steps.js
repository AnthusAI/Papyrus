const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then, setDefaultTimeout } = require("@cucumber/cucumber");

// The phone-and-desktop, light-and-dark scenario opens four browsers.
setDefaultTimeout(30_000);

const root = path.resolve(__dirname, "../..");
const browser = async (name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-related-links.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

for (const given of [
  "a Reference with no links that nobody has asked suggestions for",
  "a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference",
  "a site with no knowledge index and a Reference with one confirmed concept",
  "a concept page with two References linked by editors",
]) Given(given, function () { this.relatedResult = ""; });

for (const when of [
  "the editor opens the Related section of that Reference",
  "the editor opens the Related section",
  "the editor accepts the suggested concept",
  "the editor writes a reason and rejects the suggested Reference",
  "the editor types a hash and the start of a concept name and presses the match",
  "the editor pastes a link and then types words of a title",
  "the editor presses Suggest more and then adds a concept by its exact hashtag",
  "the editor looks at the feed card and the Reference detail header",
  "the editor opens the concept page",
  "the editor looks at the Related section at 375 and 1440 pixels",
  "the editor opens that Reference on the References page at 390 and 1440 pixels in the light and dark themes",
  "a viewer without editor access opens that Reference on the References page",
  "the editor presses Suggest more and the site reports that the Reference has no summary vector, or a reason it does not know",
  "the editor reads the explanations on the confirmed links",
  "the editor edits, cancels, clears and adds explanations on the links, and accepts a suggestion with a reason",
  "the editor reads and adds an explanation under \"Linked by editors\"",
  "a viewer without editor access reads the explanations",
  "the explanation is shown and being edited at 390 and 1440 pixels in the light and dark themes",
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
  ["referenceDates", [
    "each says \"published <date> · added <date>\" as plain text with no border",
    "a month-precision date reads \"published Oct 2026\" and a year-precision date reads \"published 2026\"",
    "a Reference with no publication date says \"published unknown\" and never shows the added date as published",
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
  ["referencesPage", [
    "the detail shows the Related section with its suggestions and the Accept and Reject buttons",
    "the Related section comes before the messages and Reference cards link to their own detail",
  ]],
  ["referencesViewer", [
    "the section says \"Editor access is required to change links.\"",
    "Suggest more and the add box are disabled",
  ]],
  ["autoSuggest", [
    "the suggestions are asked for once without a press and show as soon as the answer comes",
  ]],
  ["skipNotes", [
    "the note says \"Suggestions appear once this Reference has a summary.\" for the first",
    "the note says \"No suggestions could be made for this Reference yet.\" for the unknown reason",
    "the note never contains internal wording",
  ]],
  ["explanationsShown", [
    "each confirmed link shows its words in a block with a quote icon, and says \"Written by an editor\" with the date",
    "the suggestions show no explanation",
  ]],
  ["explanationsEdited", [
    "saving records an accept decision carrying the new words, so the link stays accepted",
  ]],
  ["explanationsCleared", [
    "cancelling saves nothing, and clearing the words offers Add explanation again",
  ]],
  ["explanationsFromReason", [
    "the reason given when accepting a suggestion becomes its explanation",
  ]],
  ["explanationsOnConceptPage", [
    "the explanation that exists is shown and the link without one offers Add explanation",
    "adding words records an accept decision with them",
  ]],
  ["explanationViewer", [
    "the explanations are readable and no Edit, Add explanation or text box is offered",
  ]],
  ["explanationShots", [
    "nothing scrolls sideways and the page raises no errors",
  ]],
  ["design", [
    "there are no borders or outlines and no drop-downs",
    "nothing scrolls sideways",
  ]],
];
for (const [scenario, thens] of outcomes) {
  for (const then of thens) Then(then, async function () { assert.ok((await browser(scenario)).includes(`passed: ${scenario}`)); });
}
