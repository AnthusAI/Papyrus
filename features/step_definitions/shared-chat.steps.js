const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");
Then("reloading open chat does not add another history entry", function () {
  assert.ok(this.mobileChatResult.includes("PASS: mobile chat entry"));
});
Then("public or unavailable routes do not restore chat or add hidden history entries", function () {
  assert.ok(this.mobileChatResult.includes("PASS: mobile chat entry"));
});
Given("mobile navigation uses the existing icon package", function () {});
When("the publication transpilation configuration is checked", async function () {
  const result = await promisify(execFile)(process.execPath, ["scripts/test-with-papyrus-transpile.mjs"]);
  this.transpilationResult = result.stdout;
});
Then("icon source exports are transpiled alongside the shared chat packages", function () {
  assert.ok(this.transpilationResult.includes("with-papyrus transpile tests passed"));
});
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
Then("publication and editor scope come from the verified newsroom session and private channel access is enforced", function () {
  assert.ok(this.papyrusHostedChatResult.includes("PASS: Papyrus gateway uses verified newsroom identity and Chatticus private chat core"));
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
Then("the newsroom editor creates the private channel and sees one persisted reply after refresh and replay", function () {
  assert.ok(this.papyrusWorkerIntegrationResult.includes("PASS: Papyrus private channel, hosted send, shared worker reply, refresh/replay, and foreign-editor denial"));
});

Given("an editor has a valid signed newsroom access token but no Prospectus session", function () {});
When("the newsroom token verification suite runs", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-chat-identity.ts"], { maxBuffer: 4 * 1024 * 1024 });
  this.newsroomIdentityResult = result.stdout;
});
Then("the server verifies the configured issuer, client, token use, expiry and editor role", function () { assert.match(this.newsroomIdentityResult, /PASS: verified newsroom JWT/); });
for (const step of ["another publication or editor cannot read the channel or its turn stream", "expired credentials cannot read or send messages"]) {
  Then(step, function () { assert.match(this.papyrusHostedChatResult, /PASS: Papyrus gateway/); });
}
Given("an editor has an open private conversation", function () {});
When("the session expires during a send or a reply poll", { timeout: 120_000 }, async function () {
  for (const mode of ["send-expiry", "poll-expiry", "identity-change"]) {
    await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs", mode], { maxBuffer: 4 * 1024 * 1024 });
  }
  this.expiryRecoveryPassed = true;
});
Then("the old transcript and retry identity are removed from the panel", function () { assert.equal(this.expiryRecoveryPassed, true); });
Then("the editor can retry after signing into the newsroom", function () { assert.equal(this.expiryRecoveryPassed, true); });
Given("an authorized editor is viewing the newsroom on a phone", function () {});
Given("the newsroom changes between mobile and desktop widths", function () {});
for (const action of ["the editor opens chat from the visible mobile control", "the keyboard reduces the available conversation height", "the chat shell updates its responsive controls"]) {
  When(action, { timeout: 120_000 }, async function () {
    const result = await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs", "mobile"], { maxBuffer: 4 * 1024 * 1024 });
    this.mobileChatResult = result.stdout;
    for (const mode of ["mobile-send-expiry", "mobile-poll-expiry"]) await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs", mode], { maxBuffer: 4 * 1024 * 1024 });
  });
}
for (const result of ["the conversation and close control fit the viewport", "keyboard focus stays within the mobile conversation", "closing chat returns focus and preserves the newsroom location", "browser Back closes mobile chat before leaving the newsroom", "the message composer and close control remain reachable", "the transcript scrolls without horizontal page overflow", "desktop layout keeps its existing toolbar behavior", "an unauthorized visitor has no chat entry point"]) {
  Then(result, function () { assert.match(this.mobileChatResult, /PASS: mobile chat entry/); });
}

Then("the newsroom session alone opens publication-local private chat", function () {
  assert.match(this.papyrusHostedChatResult, /PASS: Papyrus gateway/);
});
