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
When("the shared chat admission contract rejection suite runs", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["--experimental-strip-types", "scripts/test-shared-chat-admission.ts"], { maxBuffer: 4 * 1024 * 1024 });
  this.chatAdmissionResult = result.stdout;
});
When("Papyrus retries an uncertain Chatticus admission", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["scripts/run-papyrus-chat-admission-test.mjs"], { maxBuffer: 4 * 1024 * 1024 });
  this.papyrusAdmissionTransportResult = result.stdout;
});
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
Then("wrong trust profiles, inactive memberships and foreign transcript owners are rejected", function () {
  assert.ok(this.chatAdmissionResult.includes("trust-profile rejections, transcript ownership"));
});
Then("an identical retry returns the original result and a changed payload conflicts", function () {
  assert.ok(this.chatAdmissionResult.includes("scoped idempotency"));
});
Then("it reuses the logical message key and body with newly obtained auth headers", function () {
  assert.ok(this.papyrusAdmissionTransportResult.includes("fresh host auth, stable explicit retry key"));
});
When("the Papyrus hosted chat endpoint contract suite runs", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["scripts/run-papyrus-hosted-chat-test.mjs"], { maxBuffer: 4 * 1024 * 1024 });
  this.papyrusHostedChatResult = result.stdout;
});
Then("account and editor scope come from the sealed session and private channel access is enforced", function () {
  assert.ok(this.papyrusHostedChatResult.includes("PASS: Papyrus gateway uses sealed Prospectus identity and Chatticus private chat core"));
});
Then("the hosted chat route remains disabled until explicitly enabled", function () {
  assert.ok(this.papyrusHostedChatResult.includes("private route remains default-off"));
});
When("the Papyrus shared worker integration suite runs", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["scripts/run-papyrus-chat-worker-integration-test.mjs"], { maxBuffer: 4 * 1024 * 1024 });
  this.papyrusWorkerIntegrationResult = result.stdout;
});
When("the private console browser integration runs", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs"], { maxBuffer: 4 * 1024 * 1024 });
  this.privateChatUiResult = result.stdout;
});
Then("same-origin sends retain editor session scope, allow a pending-reply send and render the hosted reply", function () {
  assert.ok(this.privateChatUiResult.includes("shared UI sends through the private host route once"));
});
Then("the sealed editor creates the private channel and sees one persisted reply after refresh and replay", function () {
  assert.ok(this.papyrusWorkerIntegrationResult.includes("PASS: Papyrus private channel, hosted send, shared worker reply, refresh/replay, and foreign-editor denial"));
});
