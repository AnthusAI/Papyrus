import assert from "node:assert/strict";
import {
  listPapyrusPrivateChatMessages,
  openPapyrusPrivateChat,
  sendPapyrusPrivateChatMessage,
  type PapyrusPrivateChatFetch,
} from "../lib/papyrus-private-chat-client";

async function main() {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fetcher: PapyrusPrivateChatFetch = async (input, init = {}) => {
    const url = String(input);
    calls.push({ url, init });
    const payload = url.endsWith("/private-channel")
      ? { channel_id: "private / channel", participants: [{ kind: "human", actor_id: "opaque-editor" }, { kind: "bot", actor_id: "papyrus-assistant" }] }
      : url.includes("/messages") && init.method === "GET"
        ? { messages: [{ message_id: "message-1", channel_id: "private / channel", seq: 1, author_kind: "human", body: "A private draft", addressed_to_bot_id: "papyrus-assistant", created_at: "2026-10-24T00:00:00.000Z" }] }
        : { message: { message_id: "message-2", channel_id: "private / channel", seq: 2, author_kind: "human", body: "A new draft", addressed_to_bot_id: "papyrus-assistant", created_at: "2026-10-24T00:00:01.000Z" }, turn_id: "turn-1" };
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  };

  const channel = await openPapyrusPrivateChat(fetcher);
  assert.equal(channel.channel_id, "private / channel");
  const existing = await listPapyrusPrivateChatMessages(channel.channel_id, fetcher);
  assert.equal(existing[0]?.body, "A private draft");
  const sent = await sendPapyrusPrivateChatMessage(channel.channel_id, "A new draft", "stable-request-key", fetcher);
  assert.equal(sent.turn_id, "turn-1");
  assert.equal(calls.length, 3, "the adapter makes exactly one fetch per explicit operation");
  assert.equal(calls[0]?.url, "/api/newsroom/chat/private-channel");
  assert.equal(calls[0]?.init.method, "POST");
  assert.equal(calls[1]?.url, "/api/newsroom/chat/channels/private%20%2F%20channel/messages");
  assert.equal(calls[2]?.url, calls[1]?.url);
  assert.equal(calls[2]?.init.method, "POST");
  assert.equal(calls[2]?.init.credentials, "same-origin");
  assert.equal(calls[2]?.init.cache, "no-store");
  const headers = new Headers(calls[2]?.init.headers);
  assert.equal(headers.get("idempotency-key"), "stable-request-key");
  assert.equal(headers.has("authorization"), false, "this injected transport is responsible for adding credentials; the real transport obtains a fresh newsroom token");
  assert.deepEqual(JSON.parse(String(calls[2]?.init.body)), { body: "A new draft" }, "the browser sends no author, bot or tenant identity");

  let attempts = 0;
  const denied: PapyrusPrivateChatFetch = async () => {
    attempts += 1;
    return new Response(JSON.stringify({ error: "sign_in_required" }), { status: 401 });
  };
  await assert.rejects(() => openPapyrusPrivateChat(denied), /sign_in_required/);
  assert.equal(attempts, 1, "authentication failure never triggers a fallback request");
  console.log("PASS: private chat uses one same-origin request, stable explicit key, and no browser-supplied identity");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
