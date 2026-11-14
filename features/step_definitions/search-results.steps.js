const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// scripts/test-newsroom-search-results.ts (375 and 1440 pixels, a fixture page, no network) runs once for the whole feature and fails loudly if any scenario fails.
const root = path.resolve(__dirname, "../..");
let run;
const scenarios = () => (run ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-search-results.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 }).then((result) => result.stdout));

Given("a synthetic site where the word \"sound\" is in the titles of two References, the author of a third, and close in meaning to three more", function () { this.output = ""; });
for (const when of [
  "the editor opens the Search page with the word \"sound\"",
  "the editor chooses Rejected, then Pending, then Any",
  "the editor searches for words nothing contains, loses the connection, loses only meaning search, and asks for more results",
]) When(when, { timeout: 300_000 }, async function () { this.output = await scenarios(); });
for (const [then, expected] of [
  ["the three word matches come first and the three related ones follow under a Related heading, with one request made and no second search needed", "ok results"],
  ["each result is marked Title match, Word match or Related, and Pending, Accepted or Rejected, each with an icon, and nothing has a border or a dropdown", "ok results"],
  ["each choice asks the search for that state alone, says it is chosen, and lists only the matching results", "ok status"],
  ["each is said in a sentence, with a button to try again or to show any state, and more results are added without repeats", "ok states"],
]) Then(then, function () { if (!this.output.includes(expected)) throw new Error(`Expected "${expected}" in:\n${this.output}`); });
