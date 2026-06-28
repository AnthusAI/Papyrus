import { LAMBDA_DATA_AUTH_MODE, type LambdaDataClient } from "./lambda-data-client";
import { putTextModelPayload } from "./model-payloads";

export const CONSOLE_MESSAGE_KIND = "console_chat_turn";
export const CONSOLE_MESSAGE_DOMAIN = "conversation";
export const CONSOLE_NEWSROOM_FEED_KEY = "consoleChat";
export const CONSOLE_THREAD_ANCHOR_KEY = "site#papyrus";

export type EnqueueConsoleChatTurnInput = {
  threadId: string;
  threadTitle: string;
  threadSummary: string;
  primaryAnchorKind: string;
  primaryAnchorId: string;
  createdByLabel: string;
  prompt: string;
  messageSummary: string;
  source: string;
  channel: string;
  channelMetadata: Record<string, unknown>;
  threadMetadata?: Record<string, unknown>;
  responseTarget?: string;
  captureModelContext?: boolean;
  chatMessageId?: string;
};

export function defaultConsoleResponseTarget(): string {
  return (process.env.PAPYRUS_CONSOLE_RESPONSE_TARGET ?? "cloud").trim() || "cloud";
}

export async function enqueueConsoleChatTurn(
  dataClient: LambdaDataClient,
  input: EnqueueConsoleChatTurnInput,
): Promise<{ queued: true; threadId: string; chatMessageId: string; responseTarget: string }> {
  const now = new Date().toISOString();
  const responseTarget = (input.responseTarget ?? defaultConsoleResponseTarget()).trim() || "cloud";
  const threadMetadata = { channel: input.channel, ...(input.threadMetadata ?? {}) };
  const messageMetadata: Record<string, unknown> = {
    channel: input.channel,
    ...input.channelMetadata,
  };
  if (input.captureModelContext) {
    messageMetadata.captureModelContext = true;
  }

  const existingThread = await dataClient.models.MessageThread.get(
    { id: input.threadId },
    { authMode: LAMBDA_DATA_AUTH_MODE },
  );
  if (!existingThread.data) {
    const createThread = await dataClient.models.MessageThread.create(
      {
        id: input.threadId,
        threadKind: "console",
        status: "active",
        title: input.threadTitle,
        summary: input.threadSummary,
        primaryAnchorKind: input.primaryAnchorKind,
        primaryAnchorId: input.primaryAnchorId,
        primaryAnchorLineageId: input.primaryAnchorId,
        primaryAnchorKey: CONSOLE_THREAD_ANCHOR_KEY,
        createdByLabel: input.createdByLabel,
        messageCount: 0,
        metadata: JSON.stringify(threadMetadata),
        createdAt: now,
        updatedAt: now,
        newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
      } as never,
      { authMode: LAMBDA_DATA_AUTH_MODE },
    );
    if (createThread.errors?.length) {
      throw new Error(createThread.errors.map((entry) => entry?.message ?? String(entry)).join("; "));
    }
  }

  const sequenceNumber = Number(existingThread.data?.messageCount ?? 0) + 1;
  const chatMessageId = input.chatMessageId
    ?? `message-console-${input.channel}-${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;

  const createMessage = await dataClient.models.Message.create(
    {
      id: chatMessageId,
      threadId: input.threadId,
      sequenceNumber,
      role: "USER",
      messageKind: CONSOLE_MESSAGE_KIND,
      messageDomain: CONSOLE_MESSAGE_DOMAIN,
      messageType: "MESSAGE",
      status: "active",
      summary: input.messageSummary.slice(0, 180),
      source: input.source,
      authorLabel: input.createdByLabel,
      semanticLayer: "working_memory",
      searchVisibility: "private",
      responseTarget,
      responseStatus: "PENDING",
      metadata: JSON.stringify(messageMetadata),
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
    } as never,
    { authMode: LAMBDA_DATA_AUTH_MODE },
  );
  if (createMessage.errors?.length) {
    throw new Error(createMessage.errors.map((entry) => entry?.message ?? String(entry)).join("; "));
  }
  await putTextModelPayload(
    dataClient as any,
    { ownerKind: "message", ownerId: chatMessageId, ownerLineageId: chatMessageId },
    "message_body",
    "message",
    input.prompt.trim(),
    { filename: "message.txt", mediaType: "text/plain", now },
  );

  return { queued: true, threadId: input.threadId, chatMessageId, responseTarget };
}
