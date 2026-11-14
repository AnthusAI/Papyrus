const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// The browser scenario "search" in scripts/test-reference-feed.ts (375 and 1440 pixels, a fixture site, no network) runs once for the whole feature.
const root = path.resolve(__dirname, "../..");
let run;
const searchScenario = () => (run ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-reference-feed.ts", "search"], { cwd: root, maxBuffer: 8 * 1024 * 1024 }).then((result) => result.stdout));

for (const given of [
  "a synthetic site with unrated, accepted and rejected References",
  "a browser that saved Reviewed Yes as its choice",
  "a synthetic site where meaning search is unavailable",
]) Given(given, function () { this.searchResult = ""; });
for (const when of [
  "the editor types an author's full name in the search box and presses Enter",
  "the editor searches for a word that is in one unrated Reference's title",
  "the editor searches for a concept that a Reference's summary is about but its words do not contain",
  "the editor searches for a phrase that one Reference matches by its title and by meaning",
  "the editor searches, narrows Reviewed to No, and then clears the search",
  "the editor opens the References page with ?q= and a name",
  "the editor searches for words nothing contains, and then for a name that only a rated Reference has while Reviewed is No",
  "the editor searches for a word in one title",
  "the editor searches for a phrase that more than one page of References match and scrolls to the end",
  "the editor accepts the third card of a search",
]) When(when, { timeout: 300_000 }, async function () { this.searchResult = await searchScenario(); });
for (const then of [
  "the rejected Reference by that author is the one card, showing its Reject, with \"Matched: author\"",
  "the search box is above Sort and Reviewed, the address carries ?q=, and nothing scrolls sideways at 375 pixels",
  "that Reference is listed with \"Matched: title\", with the same Accept and Reject controls as in the feed",
  "there is no large lead card and no new-items pill",
  "that Reference is listed with \"Matched: meaning\"",
  "that Reference is the first card and says \"Matched: title and meaning\"",
  "the cards that match only by words or only by meaning follow it, each saying how",
  "Sort reads Relevance in place of Predictions and Newest, and Reviewed opened on Any",
  "choosing Reviewed No during the search did not change the saved choice",
  "clearing the search brings back Sort, the saved Reviewed of Yes, and a plain address",
  "the search box holds that name and its results are listed",
  "the first says no References match what was typed, in words",
  "the second says \"No matches with Reviewed No\" and offers a Show Reviewed Any button that lists the match",
  "the word results stay, with a line saying the search used words only because meaning search is unavailable",
  "a Retry button searches again, and when both parts then work the line goes",
  "when both word search and meaning search are unavailable the feed's own error appears with its Retry",
  "the next page is asked for with the site's cursor, 24 at a time, and no card appears twice",
  "it shows the answer and no card moves",
]) Then(then, { timeout: 300_000 }, async function () { assert.ok((await searchScenario()).includes("Reference feed scenario passed: search")); });
