const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (script, name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", script, ...(name ? [name] : [])], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

Given("an isolated Notification Center with a batch of three AI drafts", function () { this.notificationResult = ""; });
Given("the organizer navigation", function () { this.notificationResult = ""; });

const scenarios = [
  ["content", "the editor opens the Notification Center at 375 and 1440 pixels",
    ["every draft card shows its type, headline, dek and what happens if it is left alone, with Accept and Reject and no prediction row",
      "the header counts drafts, nothing scrolls sideways, no card has a border, and the retired Approve, Steer and Agree wording is gone",
      "opening a draft shows its headline, section, evidence, citations, a link to the full draft in Proposals and a Why box"]],
  ["decide", "the editor accepts one draft, rejects one with a Why and the \"Not this kind of story\" chip written in the detail pane, and accepts the last",
    ["each Proposal is moved to approved or declined, decided cards stay in place showing their answer, and the request stays open until the last draft is decided",
      "the request closes with every decision recorded, \"not this kind\" as its one steering signal, and the page says \"All caught up\" and lists what was decided"]],
  ["uniform", "the editor accepts all three drafts, and in another batch rejects all three",
    ["the answers are an approval and a rejection, and a plain rejection carries no steering signal"]],
  ["refusal", "a Proposal refuses the move, or a draft is on hold in Proposals",
    ["the draft stays undecided, says why in words, keeps its buttons, and nothing is recorded"]],
  ["closing", "the drafts were already decided in Proposals, or none or only some of them can be opened here",
    ["the request closes itself, takes Accept or Reject on the request, or lets the openable drafts finish it",
      "a failed load offers Try again"]],
  ["references", "the editor looks at pending References and uses the Drafts and References pills at 375 and 1440 pixels",
    ["each Reference card shows the Cyclotron's Accept or Reject with its confidence, or says there is no prediction",
      "a card opens the same detail pane the References page has, a rating is saved through the References review, and an empty pill says so"]],
  ["mixed", "the editor opens a feed that mixes a hard gate, drafts, References and a held email at 375 and 1440 pixels",
    ["the hard gate is the first card and says it is a hard gate, and no third card of one type follows two of the same while another type waits",
      "the pills count what waits for each type and a pill narrows the feed to that one type",
      "that Reference is not in the feed, it is listed under Decided automatically with an Overrule button, and the \"You're shaping this\" strip counts the week's decisions and agreements",
      "each opens in the one detail pane with a body that fits its type, a held email's text is inert and its links are not clickable, and a Reference shows our captured record",
      "nothing is moved, answered, rated or decided, and each card says what happens if it is left alone"]],
  ["email", "the editor rejects a held email with a Why written in its detail pane",
    ["the email is rejected with that reason, its card shows the answer, and nothing else is changed"]],
];

for (const [name, action, outcomes] of scenarios) {
  When(action, { timeout: 240_000 }, async function () {
    this.notificationResult = await run("scripts/test-notification-center-drafts.ts", name);
  });
  for (const outcome of outcomes) {
    Then(outcome, function () {
      assert.ok(this.notificationResult.includes(`Notification Center scenario passed: ${name}`));
    });
  }
}

When("the editor has confirmed ten of the Cyclotron's predictions and a Reference arrives that it is very sure about", { timeout: 240_000 }, async function () { this.notificationResult = await run("scripts/test-notification-center-drafts.ts", "mixed"); });
When("the editor opens a hard gate, a draft, a held email and a Reference", { timeout: 240_000 }, async function () { this.notificationResult = await run("scripts/test-notification-center-drafts.ts", "mixed"); });
When("the editor opens and reads items without deciding them", { timeout: 240_000 }, async function () { this.notificationResult = await run("scripts/test-notification-center-drafts.ts", "mixed"); });

When("the editor looks at Editorial work", { timeout: 60_000 }, async function () {
  this.notificationResult = await run("scripts/test-newsroom-organizer-nav.ts");
});
Then("Drafts opens the Proposals panel", function () {
  assert.ok(this.notificationResult.includes("PASS"));
});
