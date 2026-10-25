import { postChatMessage, type ChatHttpTransport, type ChatMessageSubmission, type PostMessageResponse } from "chatticus/chat-client";

/** Stable author mapping supplied by the Papyrus host; never infer it from a display label or email. */
export interface PapyrusChatAuthor {
  hostMappedAuthorId: string;
  addressedToBotId: string | null;
}

/** One logical send. Reuse this exact value only for an explicit retry of the same message. */
export interface PapyrusChatAdmissionAttempt {
  readonly submission: Readonly<ChatMessageSubmission>;
  readonly idempotencyKey: string;
}

export interface PapyrusChatAdmissionSenderOptions {
  /** Host-owned chat URL; no endpoint is configured or exposed by this module. */
  url: string;
  /** Must obtain current Papyrus auth headers on every call; token type stays a host decision. */
  freshAuthorizationHeaders: () => Promise<Record<string, string>>;
  fetch?: typeof globalThis.fetch;
  /** Override only in hermetic tests. Production defaults to the platform CSPRNG. */
  createIdempotencyKey?: () => string;
}

export interface PapyrusChatAdmissionSender {
  createAttempt(text: string, author: PapyrusChatAuthor): PapyrusChatAdmissionAttempt;
  send(attempt: PapyrusChatAdmissionAttempt): Promise<PostMessageResponse>;
}

/**
 * Bind Papyrus's host-owned auth and URL to Chatticus's reusable admission
 * transport. Each send makes one POST; there is no automatic retry or auth
 * fallback. An explicit retry sends the same attempt and refreshes headers.
 */
export function createPapyrusChatAdmissionSender(options: PapyrusChatAdmissionSenderOptions): PapyrusChatAdmissionSender {
  const transport: ChatHttpTransport = {
    url: options.url,
    headers: async () => {
      const headers = await options.freshAuthorizationHeaders();
      const authorization = Object.entries(headers).find(([name]) => name.toLowerCase() === "authorization")?.[1];
      if (!authorization?.trim()) throw new Error("Papyrus authorization headers are required");
      return headers;
    },
    ...(options.fetch ? { fetch: options.fetch } : {}),
  };
  const createKey = options.createIdempotencyKey ?? (() => globalThis.crypto.randomUUID());

  return {
    createAttempt(text, author) {
      if (!text.trim() || !author.hostMappedAuthorId.trim()) throw new Error("A message and host-mapped author are required");
      const submission: ChatMessageSubmission = {
        author_kind: "human",
        author_id: author.hostMappedAuthorId,
        body: text,
        addressed_to_bot_id: author.addressedToBotId,
      };
      const idempotencyKey = createKey();
      if (!idempotencyKey.trim()) throw new Error("A stable message admission key is required");
      return Object.freeze({ submission: Object.freeze(submission), idempotencyKey });
    },
    send(attempt) {
      return postChatMessage(transport, attempt.submission, attempt.idempotencyKey);
    },
  };
}
