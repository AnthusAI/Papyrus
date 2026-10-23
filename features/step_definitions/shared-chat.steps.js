const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");
Given("Papyrus supplies an editorial conversation to the shared chat", function () {});
for (const [action, mode] of [["the editor sends a new console message", "send"], ["the editor selects a tool's reference action", "reference"]]) {
  When(action, { timeout: 120_000 }, async function () {
    const result = await promisify(execFile)(process.execPath, ["scripts/test-shared-console-chat.mjs", mode], { maxBuffer: 4 * 1024 * 1024 });
    this.sharedChatResult = result.stdout;
  });
}
Then("the Papyrus adapter receives the message once and shows its reply", function () {
  assert.ok(this.sharedChatResult.includes("Papyrus shared chat send passed"));
});
Then("the shared surface renders the assistant markdown safely", function () {
  assert.ok(this.sharedChatResult.includes("Safe shared markdown passed"));
});
Then("Papyrus handles that reference action without a Chatticus account", function () {
  assert.ok(this.sharedChatResult.includes("Papyrus reference action passed"));
});
