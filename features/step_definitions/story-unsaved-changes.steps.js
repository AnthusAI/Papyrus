const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const runBrowserScenario = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-story-unsaved-changes-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of [
  "the Stories board with a draft Story",
  "the Story editor open on a published Story",
  "the Stories board with a Story whose front matter is not valid YAML",
]) Given(given, function () {});

for (const when of [
  "the editor opens the draft Story and changes its subtitle",
  "the editor opens the draft Story, changes its subtitle and presses Cancel",
  "the editor changes its subtitle and presses Save in the bar",
  "the editor opens that Story on the Edit view",
  "the editor changes the subtitle of the draft Story and closes the drawer",
  "the editor opens the draft Story on a phone and changes its subtitle",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-story-unsaved-changes-ui.ts (a real browser, local preview data).
const browserScenarioForOutcome = {
  "a bar saying \"Unsaved changes\" with Cancel and Save is in view at the bottom of the drawer, and the toolbar has one Save button": "drawer_save",
  "pressing Save saves the Story once, in place, keeps the new subtitle and the bar goes away": "drawer_save",
  "the subtitle is as it was last saved, nothing was saved and the bar goes away": "drawer_cancel",
  "the bar said that saving makes a new draft version that readers see once it is published": "published_story",
  "the Story was saved once as a new version, never in place, nothing was published, and the editor shows the new draft version": "published_story",
  "Title, Subtitle and Blurb are switched off and a note says to fix the front matter under Front matter (YAML)": "unreadable_front_matter",
  "the editor is asked whether to discard the changes, and answering no keeps the drawer open with the change": "close_drawer",
  "answering yes closes the drawer": "close_drawer",
  "the bar with Cancel and Save is in view at the bottom of the screen and nothing scrolls sideways": "phone",
};
const cucumberExpressionFor = (sentence) => sentence.replace(/[()]/g, (bracket) => `\\${bracket}`);
for (const [outcome, scenario] of Object.entries(browserScenarioForOutcome)) Then(cucumberExpressionFor(outcome), { timeout: 180000 }, async function () { await runBrowserScenario(scenario); });
