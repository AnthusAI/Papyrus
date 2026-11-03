const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// The browser scenario "quality" in scripts/test-reference-feed.ts (375 and 1440 pixels, a fixture site, no network) runs once for the whole feature.
const root = path.resolve(__dirname, "../..");
let run;
const qualityScenario = () => (run ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-reference-feed.ts", "quality"], { cwd: root, maxBuffer: 8 * 1024 * 1024 }).then((result) => result.stdout));

for (const given of [
  "a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version",
  "a synthetic site where no Reference has five stars",
  "a synthetic site where sixty archived five star References arrived after the live ones",
  ]) Given(given, function () { this.qualityResult = ""; });
for (const when of [
  "the editor chooses the Quality sort",
  "the editor chooses Newest and then the minimum 4+",
  "the editor chooses Newest and then the minimum 5",
  "the editor chooses Quality while Show is Unrated",
  "the editor has chosen a minimum of 4+ and then chooses Best bets",
  "the editor chooses Best bets, Unrated and then the minimum 3+",
  "the editor chooses the minimum 5",
  "the editor chooses Newest and the minimum 4+ and reloads the page",
  "the editor searches for a word in every title and chooses Newest, then Quality, then the minimum 4+",
  "the editor looks at the Sort, Show and Minimum stars controls",
  ]) When(when, { timeout: 300_000 }, async function () { this.qualityResult = await qualityScenario(); });
for (const then of [
  "the References appear five stars first, newest first among each number of stars, down to one star",
  "the unstarred, the archived and the replaced References are not listed",
  "every star level of every corpus was read from the stars index",
  "the five and four star References are listed together, newest arrival first",
  "only the five and four star levels were read, and not the feed's own index",
  "only the five star References are listed, newest first",
  "choosing 3+ afterwards adds the four and three star References by arrival",
  "Show reads All in view",
  "choosing Unrated afterwards lists the unrated starred References, and choosing Rated lists the rated ones",
  "the minimum reads Any and the feed lists unstarred References again",
  "Sort reads Newest and Show reads All",
  "the page says \"Nothing here has 5 stars.\" with a Show any stars button",
  "pressing it sets the minimum to Any and lists the References again",
  "Newest, All and 4+ are chosen again and the same References are listed",
  "the live References are listed after the page of archived ones is skipped, reading further pages by itself",
  "Sort reads Relevance, Newest and Quality and opens on Relevance",
  "Newest orders the matches by arrival, Quality puts the unstarred matches after the starred ones, and 4+ keeps only four and five stars",
  "the search asked for each ordering and minimum, the minimum is the saved one, and the search's own sort is not saved",
  "clearing the search brings back the saved Sort, Show and minimum",
  "the Minimum stars row is labelled, each minimum has a star icon and its number except Any, and none has a border",
  "nothing scrolls sideways at 375 pixels",
  ]) Then(then, { timeout: 300_000 }, async function () { assert.ok((await qualityScenario()).includes("Reference feed scenario passed: quality")); });
