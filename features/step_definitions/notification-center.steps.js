const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (script, name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", script, ...(name ? [name] : [])], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

Given("an isolated Notification Center with a batch of three generated ideas", function () { this.notificationResult = ""; });

const scenarios = [
  ["content", "the editor opens the Notification Center at 375 and 1440 pixels",
    ["the batch is one card that names the run's three ideas, says they wait in the Idea column and links to the Stories board, with no Accept or Reject and no prediction row",
      "the header counts the batch, nothing scrolls sideways, no card has a border, and the retired Approve, Steer and Agree wording and the words Proposed Story are gone",
      "opening the batch lists each idea with its stage, links each idea to its story and the card to the Idea column, and has no decision panel and no Why box"]],
  ["ideaBoard", "the editor looks at a batch of which one idea was moved forward and one was spiked on the board, and at a batch whose ideas have all left the Idea column, and at a batch raised before ideas were stories",
    ["the card says how many of its ideas still wait in the Idea column, a batch with none left has no card, a batch that names no story has no card, and looking decides nothing"]],
  ["references", "the editor looks at pending References and uses the Ideas and References pills at 375 and 1440 pixels",
    ["each Reference card marks the predicted Accept or Reject with its confidence, or says there is no prediction",
      "a card opens the same detail pane the References page has, a rating is saved through the References review, and an empty pill says so"]],
  ["mixed", "the editor opens a feed that mixes a hard gate, a batch of ideas, References and a held email at 375 and 1440 pixels",
    ["the hard gate is the first card and says it is a hard gate, and no third card of one type follows two of the same while another type waits",
      "the pills count what waits for each type and a pill narrows the feed to that one type",
      "that Reference is not in the feed, it is listed under Decided automatically with an Overrule button, and the \"You're shaping this\" strip counts the week's decisions and agreements",
      "each opens in the one detail pane with a body that fits its type, a held email's text is inert and its links are not clickable, and a Reference shows our captured record",
      "before anything is selected there is no Detail pane and the feed has the whole width",
      "nothing is moved, answered, rated or decided, and each card says what happens if it is left alone"]],
  ["deepLink", "the editor opens a Reference, and later follows a link to it, and a link to an item that is no longer waiting",
    ["opening an item shows its needs-me address with its id, and closing it on a phone returns the address to the overview",
      "a link to an item opens the feed with that item in the detail pane, on a desktop and on a phone",
      "a link to an item that is not waiting any more says so, with no empty pane"]],
  ["reasonFailure", "the editor writes a note after answering a hard gate and the save is refused",
    ["the page says in words that the note could not be saved and is kept, the typed text stays in the box, and tapping away saves it"]],
  ["reasonRequest", "the editor answers a hard gate and then writes its note, and writes a flag's note before acknowledging it and changes it afterwards",
    ["each note is saved onto the existing answer, the choice and the person who answered stay as they were, and the card shows the note"]],
  ["reasonOthers", "the editor rejects a held email and then writes its reason, and accepts a Reference and then writes its reason",
    ["the held email's decision is sent again with the reason so the recorded reason changes, the Reference's rating is saved again with its note, and each reopens showing its reason"]],
  ["queueBar", "the editor opens a hard gate at 1440 by 900, 1440 by 1300 and 1024 by 768 and scrolls the page and the feed, and again on a phone",
    ["the Previous and Next bar's bottom-right corner is the viewport's bottom-right corner, other sections below the feed never push it up, and on a phone it is the fixed bottom of the sheet"]],
  ["email", "the editor rejects a held email with a Why written in its detail pane",
    ["the email is rejected with that reason, its card shows the answer, and nothing else is changed"]],
];

for (const [name, action, outcomes] of scenarios) {
  When(action, { timeout: 240_000 }, async function () {
    this.notificationResult = await run("scripts/test-notification-center-feed.ts", name);
  });
  for (const outcome of outcomes) {
    Then(outcome, function () {
      assert.ok(this.notificationResult.includes(`Notification Center scenario passed: ${name}`));
    });
  }
}

When("the editor has confirmed ten of the Cyclotron's predictions and a Reference arrives that it is very sure about", { timeout: 240_000 }, async function () { this.notificationResult = await run("scripts/test-notification-center-feed.ts", "mixed"); });
When("the editor opens a hard gate, a batch of ideas, a held email and a Reference", { timeout: 240_000 }, async function () { this.notificationResult = await run("scripts/test-notification-center-feed.ts", "mixed"); });
When("the editor opens and reads items without deciding them", { timeout: 240_000 }, async function () { this.notificationResult = await run("scripts/test-notification-center-feed.ts", "mixed"); });

// The access gate's loading state: scripts/test-newsroom-loading.ts renders the skeleton and checks the gate uses it.
Given("the newsroom is still checking the editor's session", function () { this.loadingResult = ""; });
When("the Notification Center or another newsroom page is loading", async function () {
  this.loadingResult = (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-loading.ts"], { cwd: path.resolve(__dirname, "../..") })).stdout;
});
Then("the loading state is the feed's skeleton of flat tones and rounded cards, with no border, outline or rule", function () { assert.match(this.loadingResult, /newsroom loading skeleton: ok/); });
Given("the newsroom shell at 375 and 1440 pixels", function () { this.chromeResult = ""; });
When("the editor looks at the top bar, the sidebar, the account button and the bottom navigation", async function () { this.chromeResult = await run("scripts/test-newsroom-chrome.ts"); });
for (const text of [
  "none of them has a border, an outline or a rule, and the controls are tone fills in rounded rectangles",
  "the bar has one search field and no second search button",
  "on a phone the bar shows the search field and the account button only, with no cut-off page title, because the page's own heading names it and Settings is in the account menu",
]) Then(text, function () { assert.match(this.chromeResult, /newsroom chrome: ok/); });
Then("when the feed loads it replaces the skeleton in place, in the same shapes", function () { assert.match(this.loadingResult, /newsroom loading skeleton: ok/); });
When("the editor opens the board and its records are still loading", async function () {
  this.loadingResult = (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-loading.ts"], { cwd: path.resolve(__dirname, "../..") })).stdout;
});
Then("the board shows three columns of pulsing cards in flat tones and rounded rectangles, with no border, outline or rule", function () { assert.match(this.loadingResult, /newsroom loading skeleton: ok/); });

// Sign-in keeps the deep link: the access gate passes no fixed return path, so the page that asked is stored and loaded after sign-in.
Then("signing in from a deep link comes back to that link, not to the overview", function () {
  const gate = fs.readFileSync(path.join(root, "components/newsroom-access-gate.tsx"), "utf8");
  const control = fs.readFileSync(path.join(root, "components/reader-auth-control.tsx"), "utf8");
  assert.match(gate, /<ReaderAuthControl showIdentity \/>/);
  assert.match(control, /window\.location\.replace\(nextPath\)/);
});
