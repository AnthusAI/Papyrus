const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const exec = async (args) => (await promisify(execFile)(process.execPath, ["--import", "tsx", ...args], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
const browser = (name) => exec(["scripts/test-messages-page.ts", name]);

for (const given of [
  "a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record",
  "a Messages page with more conversations than fit on one page",
  "the Messages page helpers",
]) Given(given, function () {});
for (const when of [
  "the editor opens the page",
  "the editor taps References, Stories, Chats and Other in turn",
  "the editor looks at a Reference conversation",
  "the editor replies to a message and then adds a message in the card",
  "the editor writes in the New message box and taps Post",
  "the editor opens Other",
  "the editor taps Show more conversations",
  "the editor looks at the page at 375 and 1440 pixels",
  "streams of conversations are merged and messages are trimmed",
]) When(when, function () {});

// Each outcome runs the named browser scenario in scripts/test-messages-page.ts (every one covers 375 and 1440 pixels).
const outcomes = [
  ["all", [
    "All is selected and the conversations are in order of their last activity",
    "the machine record is not listed",
    "the sections are buttons with icons and there are no drop-downs",
  ]],
  ["sections", [
    "each shows only its own conversations, with the Story's title, stage and link, and an Open chat button",
    "the New message box is on All and Other only",
    "an empty section says so in plain words with an icon",
  ]],
  ["reference", [
    "the messages come first and the Reference is below with its picture, headline and dek",
    "the Reference has no decision controls and opens the Reference",
    "only the latest messages show until the editor taps Show all with the count",
  ]],
  ["reply", [
    "the reply is nested under the message and saved in that conversation with its parent",
    "a refused save takes the message back, says so in words with an icon, and keeps the typed text",
  ]],
  ["start", ["a new conversation appears first, attached to nothing, and the box clears"]],
  ["forum", ["the forum thread is a card with its message count and an Open thread link to its own view"]],
  ["paging", ["the next page follows in order with no conversation twice"]],
  ["design", ["nothing has a border, an outline or a rule and nothing scrolls sideways"]],
];
for (const [scenario, thens] of outcomes) {
  for (const then of thens) Then(then, async function () { assert.ok((await browser(scenario)).includes(`passed: ${scenario}`)); });
}

const helpers = () => exec(["--test", "scripts/test-conversation-feed.ts"]);
Then("newest activity comes first across streams and pages", async function () { assert.match(await helpers(), /merge newest activity first across pages/); });
Then("only the latest messages show, with the rest counted", async function () { assert.match(await helpers(), /newest messages show/); });
