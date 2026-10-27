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
    ["every draft shows its headline, dek, section, evidence line, linked sources and a link to its full draft in Proposals",
      "every draft has large Accept and Reject buttons and a full-width Why box, and nothing scrolls sideways",
      "the header counts AI drafts to review and the retired Approve, Steer and Agree wording is gone"]],
  ["decide", "the editor accepts one draft, rejects one as not this kind of story with a Why, and accepts the last",
    ["each Proposal is moved to approved or declined and the request stays open until the last draft is decided",
      "the request closes with every decision recorded and \"not this kind\" as its one steering signal"]],
  ["uniform", "the editor accepts all three drafts, and in another batch rejects all three",
    ["the answers are an approval and a rejection, and a plain rejection carries no steering signal"]],
  ["refusal", "a Proposal refuses the move, or a draft is on hold in Proposals",
    ["the draft stays undecided, says why in words, keeps its buttons, and nothing is recorded"]],
  ["closing", "the drafts were already decided in Proposals, or none or only some of them can be opened here",
    ["the request closes itself, takes Accept or Reject on the request, or lets the openable drafts finish it",
      "a failed load offers Try again, and a request with no deadline says so plainly"]],
  ["needs_attention", "the editor looks at pending references in Needs attention at 375 and 1440 pixels",
    ["each shows the Cyclotron's Accept or Reject with its confidence, or says there is no prediction",
      "the row opens the reference review queue and the suggestion itself is read only"]],
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

When("the editor looks at Editorial work", { timeout: 60_000 }, async function () {
  this.notificationResult = await run("scripts/test-newsroom-organizer-nav.ts");
});
Then("Drafts opens the Proposals panel", function () {
  assert.ok(this.notificationResult.includes("PASS"));
});
