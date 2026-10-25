import assert from "node:assert/strict";
import { createPapyrusChatAdmissionSender } from "../lib/papyrus-chat-admission";

async function main() {
  const sent: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  let headerCalls = 0;
  let keyCalls = 0;
  let fetchCalls = 0;
  const sender = createPapyrusChatAdmissionSender({
    url: "https://papyrus-chat.example.invalid/messages",
    freshAuthorizationHeaders: async () => {
      headerCalls += 1;
      return { Authorization: `Bearer papyrus-session-${headerCalls}` };
    },
    createIdempotencyKey: () => `papyrus-message-key-${String(++keyCalls).padStart(8, "0")}`,
    fetch: async (input, init) => {
      fetchCalls += 1;
      sent.push({ input, init });
      if (fetchCalls === 1) return new Response("temporary failure", { status: 503 });
      return Response.json({ message: { id: "message-1" }, turn_id: "turn-1" });
    },
  });

  const attempt = sender.createAttempt("Find the recent draft", {
    hostMappedAuthorId: "papyrus-host-author-42",
    addressedToBotId: "papyrus-editorial-assistant",
  });
  await assert.rejects(sender.send(attempt), /HTTP 503: temporary failure/);
  assert.equal(fetchCalls, 1, "an uncertain response does not trigger an automatic retry");
  assert.equal(headerCalls, 1, "first send obtains current host auth once");

  const result = await sender.send(attempt);
  assert.deepEqual(result, { message: { id: "message-1" }, turn_id: "turn-1" });
  assert.equal(fetchCalls, 2, "the explicit retry sends exactly one more request");
  assert.equal(headerCalls, 2, "retry obtains fresh Papyrus auth headers");
  assert.equal(keyCalls, 1, "retry reuses the same logical-message key");
  assert.deepEqual(sent.map(({ input }) => input), ["https://papyrus-chat.example.invalid/messages", "https://papyrus-chat.example.invalid/messages"]);

  const firstInit = sent[0].init;
  const retryInit = sent[1].init;
  assert.equal(firstInit?.method, "POST");
  assert.equal(retryInit?.method, "POST");
  const firstHeaders = new Headers(firstInit?.headers);
  const retryHeaders = new Headers(retryInit?.headers);
  assert.equal(firstHeaders.get("Authorization"), "Bearer papyrus-session-1");
  assert.equal(retryHeaders.get("Authorization"), "Bearer papyrus-session-2");
  assert.equal(firstHeaders.get("Idempotency-Key"), attempt.idempotencyKey);
  assert.equal(retryHeaders.get("Idempotency-Key"), attempt.idempotencyKey);
  assert.equal(firstHeaders.get("Content-Type"), "application/json");
  assert.equal(firstInit?.body, retryInit?.body, "explicit retry preserves the exact submission body");
  assert.deepEqual(JSON.parse(String(firstInit?.body)), {
    author_kind: "human",
    author_id: "papyrus-host-author-42",
    body: "Find the recent draft",
    addressed_to_bot_id: "papyrus-editorial-assistant",
  });

  const otherAttempt = sender.createAttempt("Read a separate draft", {
    hostMappedAuthorId: "papyrus-host-author-42",
    addressedToBotId: "papyrus-editorial-assistant",
  });
  assert.notEqual(otherAttempt.idempotencyKey, attempt.idempotencyKey, "a new logical message gets a new key");
  assert.equal(keyCalls, 2);

  let unauthorizedFetches = 0;
  const authFailureSender = createPapyrusChatAdmissionSender({
    url: "https://papyrus-chat.example.invalid/messages",
    freshAuthorizationHeaders: async () => { throw new Error("host auth unavailable"); },
    fetch: async () => { unauthorizedFetches += 1; return Response.json({}); },
    createIdempotencyKey: () => "papyrus-message-key-auth-failure",
  });
  const authFailureAttempt = authFailureSender.createAttempt("Do not fall back", {
    hostMappedAuthorId: "papyrus-host-author-42",
    addressedToBotId: null,
  });
  await assert.rejects(authFailureSender.send(authFailureAttempt), /host auth unavailable/);
  assert.equal(unauthorizedFetches, 0, "auth failure invokes no anonymous or fallback request");

  const emptyAuthSender = createPapyrusChatAdmissionSender({
    url: "https://papyrus-chat.example.invalid/messages",
    freshAuthorizationHeaders: async () => ({}),
    fetch: async () => { unauthorizedFetches += 1; return Response.json({}); },
    createIdempotencyKey: () => "papyrus-message-key-empty-auth",
  });
  await assert.rejects(emptyAuthSender.send(emptyAuthSender.createAttempt("No anonymous send", {
    hostMappedAuthorId: "papyrus-host-author-42",
    addressedToBotId: null,
  })), /Papyrus authorization headers are required/);
  assert.equal(unauthorizedFetches, 0, "missing Authorization cannot fall back to anonymous transport");

  console.log("PASS: Papyrus Chatticus admission adapter uses fresh host auth, stable explicit retry key and one POST per attempt");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
