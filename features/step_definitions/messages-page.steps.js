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
  "the editor taps List and reloads the page",
  "the editor looks at the Reference and Story threads",
  "the editor taps References, Stories, Chats and Other in turn",
  "the editor selects a Reference thread at 375, 768, 834, 1024 and 1440 pixels",
  "the editor opens an address that names a thread, even one on a later page, or one that does not exist",
  "the editor taps Rename, changes the title and taps Save",
  "the editor replies to a message and then adds a message in the open conversation",
  "the editor writes a message in the New message box and then gives it a title and taps Post",
  "the editor opens a conversation whose authors have profiles",
  "another editor opens a conversation written by someone else",
  "the author taps Edit on their message, changes the text and taps Save",
  "the author taps Delete on a message that has a reply and confirms",
  "an admin opens a conversation written by others",
  "the backend refuses an edit and a delete",
  "the editor opens Other and Chats",
  "the editor taps Show more conversations",
  "the editor looks at the grid, the list and an open conversation at 375, 1024 and 1440 pixels",
  "streams of conversations are merged and messages are trimmed",
]) When(when, function () {});

// Each outcome runs the named browser scenario in scripts/test-messages-page.ts (at the widths the scenario names).
const outcomes = [
  ["all", [
    "All is selected, the threads are in order of their last activity, and the machine record is not listed",
    "the sections are buttons with icons and there are no drop-downs",
    "each card shows its own title, what it is attached to, its message count, who spoke last and the latest message's first line",
    "a card holds no conversation and no messages were read for the page",
  ]],
  ["layout", [
    "every thread is one line, the List button is pressed, and the page opens in list again",
    "the page still works when the browser refuses to store the choice",
  ]],
  ["titles", ["each shows the thread's title, with the Reference's headline or the Story's title and stage as a small line below it"]],
  ["sections", [
    "each shows only its own threads and the New message box is on All and Other only",
    "an empty section says so in plain words with an icon",
  ]],
  ["detail", [
    "the address holds the thread and the whole conversation shows with the Reference's header and no decision controls",
    "at 1024 and 1440 pixels the list stays on the left with the conversation in a pane on the right",
    "at 375, 768 and 834 pixels the conversation replaces the list at the full width and Back returns to the list and clears the address",
    "only the open thread's messages were read",
  ]],
  ["link", ["the thread opens, or the page says in words that it could not be found"]],
  ["rename", [
    "the new title shows in the conversation and in the list",
    "a refused save says why in words with an icon and keeps the typed text",
  ]],
  ["reply", [
    "the reply is nested under the message and saved in that conversation with its parent",
    "the thread's card counts the new messages and moves to the top",
    "a refused save takes the message back, says so in words with an icon, and keeps the typed text",
  ]],
  ["authors", [
    "each message shows its author's profile name, or the saved label's first part when the profile cannot be read",
    "the profiles were asked for in one request for the whole conversation",
  ]],
  ["others", [
    "no message shows Edit or Delete, every message still shows Reply, and the title has no Rename",
    "the author sees Edit and Delete, each with an icon and a word, on their own messages only",
  ]],
  ["edit", ["the message shows the new text and says when it was edited, and Cancel leaves it as it was"]],
  ["delete", [
    "Delete this message? is asked inline with Delete and Keep, and Keep changes nothing",
    "the message reads Message deleted with a ban icon and offers no Reply, Edit or Delete, its reply stays, and the thread's count does not drop",
  ]],
  ["admin", ["every message shows Delete and none shows Edit, and the admin can rename any thread"]],
  ["refused", ["each says why in words with an icon, the edit box keeps the typed text, and the message is unchanged"]],
  ["start", ["Post waits for the title and says so in words, and the new thread appears first with that title and attached to nothing"]],
  ["forum", ["the forum thread links to its own view, the chat opens in the console, and neither opens a pane here"]],
  ["paging", ["the next page follows in order with no conversation twice"]],
  ["design", ["nothing has a border, an outline or a rule, nothing scrolls sideways, and lines stay one line beside the pane"]],
];
for (const [scenario, thens] of outcomes) {
  for (const then of thens) Then(then, async function () { assert.ok((await browser(scenario)).includes(`passed: ${scenario}`)); });
}

const helpers = () => exec(["--test", "scripts/test-conversation-feed.ts"]);
Then("newest activity comes first across streams and pages", async function () { assert.match(await helpers(), /merge newest activity first across pages/); });
Then("only the latest messages show, with the rest counted", async function () { assert.match(await helpers(), /newest messages show/); });
