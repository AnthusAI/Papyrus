const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");
Given("Papyrus supplies an editorial conversation to the shared chat", function () {});
for (const [action, mode] of [
  ["the editor sends a new console message", "send"],
  ["the editor selects a tool's reference action", "reference"],
  ["the editor sends a new console message with the keyboard", "keyboard-send"],
  ["the editor attempts to send a message with the keyboard", "disabled-send"],
]) {
  When(action, { timeout: 120_000 }, async function () {
    const result = await promisify(execFile)(process.execPath, ["scripts/shared-console-chat-fixture.mjs", mode], { maxBuffer: 4 * 1024 * 1024 });
    this.sharedChatResult = result.stdout;
  });
}
Given("the assistant is still replying to the previous message", function () {});
Given("Papyrus has temporarily disabled sending", function () {});
Then("Papyrus receives no message", function () {
  assert.ok(this.sharedChatResult.includes("Papyrus disabled send passed"));
});
Then("the Papyrus adapter receives the message once and shows its reply", function () {
  assert.match(this.sharedChatResult, /Papyrus (?:shared chat|pending reply|keyboard) send passed/);
});
Then("the shared surface renders the assistant markdown safely", function () {
  assert.ok(this.sharedChatResult.includes("Safe shared markdown passed"));
});
Then("Papyrus handles that reference action without a Chatticus account", function () {
  assert.ok(this.sharedChatResult.includes("Papyrus reference action passed"));
});
