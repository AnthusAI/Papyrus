const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (script, name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", script, ...(name ? [name] : [])], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
const browser = (name) => run("scripts/test-conversations.ts", name);
const helpers = async () => (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-conversation-lib.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

for (const given of [
  "a Reference open for review with no messages yet",
  "a Reference open for review with one message",
  "a Reference open for review with a message, a reply, a reply to that reply, and a second message",
  "a Reference open for review where the backend refuses to save",
  "a feed of References where one has three messages, one has one and one has none",
  "a Reference open for review with several messages and a reply box open",
  "the conversation helpers",
]) Given(given, function () { this.conversationResult = ""; });

for (const when of [
  "the editor writes a message and taps Post",
  "the editor taps Reply on it, writes a reply and taps Reply",
  "the editor opens the conversation",
  "the editor opens the feed",
  "the editor looks at the conversation at 375 and 1440 pixels",
  "they build keys, number messages, nest replies and write",
]) When(when, function () { this.conversationResult = ""; });

// Each outcome runs the named browser scenario in scripts/test-conversations.ts (every one covers 375 and 1440 pixels).
const outcomes = [
  ["post", [
    "the message shows at once, marked as sending in words, and the box clears",
    "the saved message names its author without the full address",
    "the message is saved in the conversation of that Reference",
    "the feed's message count follows what is written",
  ]],
  ["reply", [
    "the reply sits under that message and the reply box closes",
    "the reply is saved with the message it answers as its parent",
  ]],
  ["flat", [
    "there are two top-level messages and both replies sit under the first, one level deep",
    "the reply to a reply says \"In reply to\" and the name of the author it answers, with an icon",
    "a new reply to that reply lands under the same top-level message",
  ]],
  ["failure", [
    "the message is taken back out of the list",
    "the failure is said in words with an icon, never by colour alone",
    "what the editor typed is still in the box",
  ]],
  ["count", [
    "a card with messages shows a message icon and the number, labelled with the count in words",
    "a card with no messages shows no count",
  ]],
  ["design", [
    "no message, box or button has a border, an outline or a rule",
    "there are no drop-downs and nothing scrolls sideways",
  ]],
];
for (const [scenario, thens] of outcomes) {
  for (const then of thens) Then(then, async function () { assert.ok((await browser(scenario)).includes(`passed: ${scenario}`)); });
}

// The pure helpers: scripts/test-conversation-lib.ts.
Then("the anchor key names the Reference, and one thread id follows from it", async function () { assert.match(await helpers(), /The anchor key names the thing the conversation is about/); });
Then("a create that loses the race for its sequence number retries with the next number", async function () { assert.match(await helpers(), /retries with the next one/); });
Then("a thread that two editors start at once is shared, not split", async function () { assert.match(await helpers(), /a lost create race uses the winner's/); });
Then("replies nest one level deep", async function () { assert.match(await helpers(), /Replies nest one level under their top-level message/); });
