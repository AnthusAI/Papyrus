const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-story-type-editor.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of [
  "a Story open in the editor on a site that offers the types article, post and guide",
  "a published Story open in the editor on a site that offers the types article, post and guide",
  "a Story open in the editor on a site that declares no Story types",
  "a Story open in the editor on a phone",
]) Given(given, function () {});

for (const when of [
  "the editor chooses the Post button",
  "the editor chooses the Guide button",
  "the editor chooses Post, saves a new version and publishes it",
  "the editor saves a new version of it as a Guide",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-story-type-editor.ts (a real browser, the local-preview backend, no network).
const outcomes = {
  "the types are buttons with a check on the chosen one, there is no dropdown, and the Story is now a post under the posts address": "buttons_not_a_dropdown",
  "the editor says in plain words that the Story has no public URL, and choosing Post takes the note away": "no_public_url",
  "saving in place was off, the live address stayed until the new version was published, and publishing said that the address moved": "live_story",
  "Publish is off and the editor says it would remove the live page": "live_story_to_a_type_without_a_page",
  "only the article type and the page are offered": "a_site_that_declares_nothing",
  "every type button is at least forty pixels tall and nothing scrolls sideways": "phone",
};
for (const [outcome, scenario] of Object.entries(outcomes)) Then(outcome, { timeout: 120000 }, async function () { await browser(scenario); });
