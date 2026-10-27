import { newsroomChatFetch } from "./newsroom-chat-client";
export type PapyrusPrivateChatChannel = {
  channel_id: string;
  participants: Array<{ kind: string; actor_id: string }>;
};

export type PapyrusPrivateChatMessage = {
  message_id: string;
  channel_id: string;
  seq: number;
  author_kind: "human" | "bot";
  body: string;
  addressed_to_bot_id: string | null;
  created_at: string;
};

export type PapyrusPrivateChatSendResult = {
  message: PapyrusPrivateChatMessage;
  turn_id: string | null;
};

export type PapyrusPrivateChatFetch = typeof globalThis.fetch;

const CHAT_API = "/api/newsroom/chat";

async function requestJson<T>(path: string, init: RequestInit, fetcher: PapyrusPrivateChatFetch): Promise<T> {
  const response = await fetcher(`${CHAT_API}/${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
  });
  const payload = await response.json().catch(() => null) as Record<string, unknown> | null;
  if (!response.ok) {
    if (response.status === 401) throw new Error("sign_in_required");
    if (response.status === 403) throw new Error("chat_account_access_denied");
    const error = typeof payload?.error === "string" ? payload.error
      : typeof payload?.detail === "string" ? payload.detail
        : `Private chat request failed (${response.status}).`;
    throw new Error(error);
  }
  if (!payload || typeof payload !== "object") throw new Error("Private chat returned an invalid response.");
  return payload as T;
}

/** Open the current editor's server-derived private channel using the verified publication-local newsroom identity. */
export async function openPapyrusPrivateChat(fetcher: PapyrusPrivateChatFetch = newsroomChatFetch): Promise<PapyrusPrivateChatChannel> {
  const result = await requestJson<PapyrusPrivateChatChannel>("private-channel", { method: "POST" }, fetcher);
  if (!result.channel_id?.trim() || !Array.isArray(result.participants)) {
    throw new Error("Private chat returned an invalid channel.");
  }
  return result;
}

/** Read only the private channel returned by the host's authenticated open request. */
export async function listPapyrusPrivateChatMessages(
  channelId: string,
  fetcher: PapyrusPrivateChatFetch = newsroomChatFetch,
): Promise<PapyrusPrivateChatMessage[]> {
  if (!channelId.trim()) throw new Error("A private chat channel is required.");
  const result = await requestJson<{ messages?: unknown }>(`channels/${encodeURIComponent(channelId)}/messages`, { method: "GET" }, fetcher);
  if (!Array.isArray(result.messages)) throw new Error("Private chat returned an invalid message list.");
  return result.messages as PapyrusPrivateChatMessage[];
}

/** One explicit send. The browser sends neither its tenant nor author or bot identity. */
export async function sendPapyrusPrivateChatMessage(
  channelId: string,
  body: string,
  idempotencyKey: string,
  fetcher: PapyrusPrivateChatFetch = newsroomChatFetch,
): Promise<PapyrusPrivateChatSendResult> {
  if (!channelId.trim() || !body.trim() || !idempotencyKey.trim()) {
    throw new Error("A channel, message and idempotency key are required.");
  }
  const result = await requestJson<PapyrusPrivateChatSendResult>(`channels/${encodeURIComponent(channelId)}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": idempotencyKey },
    body: JSON.stringify({ body }),
  }, fetcher);
  if (!result.message?.message_id || result.message.channel_id !== channelId) {
    throw new Error("Private chat returned an invalid sent message.");
  }
  return result;
}
