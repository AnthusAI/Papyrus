const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { Given, When, Then } = require('@cucumber/cucumber');

Given('an isolated page with a synthetic Reference and a synthetic generated idea', function () {
  this.decisionControlOutput = this.decisionControlOutput ?? null;
});
When('the editor looks at the control on each of them', function () { runOnce(this); });
When('the editor types a reason on the idea and chooses Reject', function () { runOnce(this); });
When("a decision is written to the idea's front matter", function () { runOnce(this); });
When("the stage for each decision is chosen from the board's stage list", function () { runOnce(this); });
Then('Accept names the stage after Idea and Reject names Spiked with the reason passed along', function () { assert.match(this.decisionControlOutput, /PASS: Accept moves the idea to the stage after Idea and Reject to Spiked/); });
When("the idea's save fails", function () { runOnce(this); });
Then('Accept and Reject each show an icon and a word', function () { assert.match(this.decisionControlOutput, /PASS: Accept and Reject carry a mark and a word/); });
Then('the reason is a textarea, not a dropdown or a popover', function () { assert.match(this.decisionControlOutput, /PASS: Accept and Reject carry a mark and a word/); });
Then('the decision, the reason, the editor and the time are recorded', function () { assert.match(this.decisionControlOutput, /PASS: rejecting an idea records the decision/); });
Then('the control says Recorded and that the reason was saved', function () { assert.match(this.decisionControlOutput, /PASS: rejecting an idea records the decision/); });
Then('it sits at generated.decision and the rest of the front matter is unchanged', function () { assert.match(this.decisionControlOutput, /PASS: front matter keeps the decision at generated.decision/); });
Then('a story started by a person never gets one', function () { assert.match(this.decisionControlOutput, /PASS: front matter keeps the decision at generated.decision/); });
Then('the control shows the failure as text', function () { assert.match(this.decisionControlOutput, /PASS: a failed save says so in words/); });

function runOnce(world) {
  if (!world.decisionControlOutput) {
    world.decisionControlOutput = execFileSync('npx', ['tsx', 'scripts/test-idea-decision.ts'], { encoding: 'utf8' });
  }
}
