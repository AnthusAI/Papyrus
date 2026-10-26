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

Given("an editor has a valid signed newsroom access token but no Prospectus session", function () {});
Given("the connected editor has not selected a publishing Account", function () {});
Given("an editor has matching newsroom and Prospectus identities and a selected Account", function () {});
When("the editor connects private chat", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-chat-identity.ts"], { maxBuffer: 4 * 1024 * 1024 });
  this.newsroomIdentityResult = result.stdout;
  await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs", "connection"], { maxBuffer: 4 * 1024 * 1024 });
});
for (const step of ["the server verifies the configured issuer, client, token use, expiry and editor role", "the Google sign-in challenge is bound to that editor's verified subject", "a callback for another subject is rejected before resolving a person"]) {
  Then(step, function () { assert.match(this.newsroomIdentityResult, /PASS: verified newsroom JWT/); });
}
When("the editor opens private chat", { timeout: 120_000 }, async function () {
  const result = await promisify(execFile)(process.execPath, ["scripts/run-papyrus-hosted-chat-test.mjs"], { maxBuffer: 4 * 1024 * 1024 });
  this.connectedChatResult = result.stdout;
  await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs", "selection"], { maxBuffer: 4 * 1024 * 1024 });
});
for (const step of ["the response requests validated publishing Account selection instead of another sign-in", "no channel, message or model run is created", "fresh Account membership and console permission are required", "another editor cannot read the channel or its turn stream"]) {
  Then(step, function () { assert.match(this.connectedChatResult, /PASS: Papyrus gateway/); });
}
Given("an editor has an open private conversation", function () {});
When("the session expires during a send or a reply poll", { timeout: 120_000 }, async function () {
  for (const mode of ["send-expiry", "poll-expiry"]) {
    await promisify(execFile)(process.execPath, ["scripts/private-chat-ui-fixture.mjs", mode], { maxBuffer: 4 * 1024 * 1024 });
  }
  this.expiryRecoveryPassed = true;
});
Then("the old transcript and retry identity are removed from the panel", function () { assert.equal(this.expiryRecoveryPassed, true); });
Then("the editor can reconnect or choose an authorized Account", function () { assert.equal(this.expiryRecoveryPassed, true); });
Given("an editor previously read their private transcript", function () {});
When("the publishing Account membership is revoked", { timeout: 120_000 }, async function () {
  await promisify(execFile)(process.execPath, ["scripts/run-papyrus-hosted-chat-test.mjs"], { maxBuffer: 4 * 1024 * 1024 });
  this.revokedMembershipDenied = true;
});
Then("subsequent transcript reads and sends are denied without creating a message", function () { assert.equal(this.revokedMembershipDenied, true); });
