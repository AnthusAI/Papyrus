const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = async (name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-needs-me-links.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

for (const given of [
  "an isolated Needs me feed with four suggested links",
  "an isolated Needs me feed with four suggested links read two at a time",
  "an isolated Needs me feed whose first save is refused",
  "an isolated Needs me feed that reads links through the page's related-links store",
  "a stand-in suggestion index that returns two pages of open suggestions already in order of close match",
]) Given(given, function () { this.linksResult = ""; });

for (const when of [
  "the Needs me queue reads its first page and then the page after it",
  "the editor opens the Links pill at 390 and 1440 pixels",
  "the editor presses \"Load more link suggestions\"",
  "the editor opens the first suggestion on a wide screen and on a phone",
  "the editor writes a reason, accepts the first suggestion and presses Next",
  "the editor rejects the first suggestion with a reason on the page's own related-links store",
  "the editor rejects the first suggestion, sees the refusal and rejects it again",
  "the editor opens the suggestion that names a concept",
  "the editor opens a card on a phone",
  "the editor opens a card on a screen only 560 pixels tall and scrolls the detail to its end",
  "the editor opens a card on a phone and presses Escape",
]) When(when, function () { this.linksResult = ""; });

// Each outcome runs the named browser scenario in scripts/test-needs-me-links.ts.
const outcomes = [
  ["unit", [
    "each page is one request to the open-suggestion index, asking for the highest close match first, carrying the cursor the last page returned",
    "the suggestions keep the order the index gave and one whose References cannot be shown is left out rather than shown as an id",
    "nothing is read on, filtered or re-ranked in the browser, and an empty index is an empty queue",
  ]],
  ["queue", [
    "each suggestion is a card of the type \"Link suggestion\" with Accept and Reject, ordered by close match from 0.91 down",
    "the header says how many link suggestions are waiting and the other pills leave them out",
    "nothing scrolls sideways, there are no drop-downs and every icon is a Lucide icon",
  ]],
  ["more", [
    "only the first page was read on arrival and the next page is read from where the first ended",
    "the new suggestions are placed in the feed at once and the button goes when the queue ends",
  ]],
  ["detail", [
    "the two References sit side by side on the wide screen and one above the other on the phone, each with its host and \"published <date> · added <date>\"",
    "the shared Accept and Reject buttons and the optional Why box are there, with no drop-down",
    "the decide-link action is called with the relation, the accept decision and the reason",
    "the decided suggestion says so and the next suggestion opens",
  ]],
  ["context", [
    "the decision goes through the related-links store's own decide, exactly as the Related section calls it",
  ]],
  ["reject", [
    "nothing was recorded by the refused save and the second save records a reject with no note",
  ]],
  ["concept", [
    "the concept is a chip with a hash icon and its hashtag beside the Reference with both of its dates",
  ]],
  ["sheet", [
    "the sheet is exactly the viewport, with nothing of the index showing, the header at the top and Previous and Next at the bottom edge",
    "the body fills the space between them rather than a fraction of it, and the sheet has no border and no rounded corners",
    "the sheet is gone",
  ]],
  ["sheetScroll", [
    "the detail scrolls inside the sheet and the Previous and Next bar does not move from the bottom edge",
  ]],
];
for (const [scenario, thens] of outcomes) {
  for (const then of thens) Then(then, async function () { assert.ok((await browser(scenario)).includes(`passed: ${scenario}`)); });
}
