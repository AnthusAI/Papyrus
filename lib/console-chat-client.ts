"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { configureAmplifyClient } from "../components/amplify-client-provider";
import { LINK_MESSAGE_HASHTAGS_MUTATION, messageHasHashtag, postMessageArguments, postMessageMutation } from "./post-message";
import { loadModelPayloadsForOwner, uploadModelPayloadForOwner } from "../components/news-desk-taxonomy-client";

const USER_POOL_AUTH_MODE = "userPool";
const DEFAULT_CONSOLE_THREAD_ANCHOR_KEY = "site#papyrus";
const CONSOLE_MAX_MESSAGES = 5000;
const CONSOLE_PAGE_SIZE = 300;
const CONSOLE_TOOL_CALL_KIND = "console_tool_call";
const CONSOLE_TOOL_RESULT_KIND = "console_tool_result";

const CONSOLE_THREAD_FIELDS = `
  id
  threadKind
  status
  title
  summary
  primaryAnchorKind
  primaryAnchorId
  primaryAnchorLineageId
  primaryAnchorKey
  createdByLabel
  messageCount
  lastMessageId
  lastMessageAt
  contextDigest
  metadata
  createdAt
  updatedAt
  newsroomFeedKey
`;

const CONSOLE_MESSAGE_FIELDS = `
  id
  threadId
  parentMessageId
  sequenceNumber
  role
  messageKind
  messageType
  content
  summary
  responseStatus
  responseOwner
  responseStartedAt
  responseCompletedAt
  responseError
  authorUserProfileId
  metadata
  createdAt
  updatedAt
`;

const LIST_CONSOLE_THREADS = `
  query ListMessageThreads(
    $limit: Int
    $nextToken: String
  ) {
    listMessageThreads(
      limit: $limit
      nextToken: $nextToken
    ) {
      items {
        ${CONSOLE_THREAD_FIELDS}
      }
      nextToken
    }
  }
`;

const LIST_CONSOLE_MESSAGES_BY_THREAD = `
  query ListMessagesByThreadAndSequence(
    $threadId: ID!
    $limit: Int
    $nextToken: String
  ) {
    listMessagesByThreadAndSequence(
      threadId: $threadId
      limit: $limit
      nextToken: $nextToken
    ) {
      items {
        ${CONSOLE_MESSAGE_FIELDS}
      }
      nextToken
    }
  }
`;

const UPDATE_CONSOLE_MESSAGE = `
  mutation UpdateMessage($input: UpdateMessageInput!) {
    updateMessage(input: $input) {
      ${CONSOLE_MESSAGE_FIELDS}
    }
  }
`;

const CREATE_CONSOLE_THREAD = `
  mutation CreateMessageThread($input: CreateMessageThreadInput!) {
    createMessageThread(input: $input) {
      ${CONSOLE_THREAD_FIELDS}
    }
  }
`;

const UPDATE_CONSOLE_THREAD = `
  mutation UpdateMessageThread($input: UpdateMessageThreadInput!) {
    updateMessageThread(input: $input) {
      ${CONSOLE_THREAD_FIELDS}
    }
  }
`;

export type ConsoleChatThread = {
  id: string;
  threadKind: string;
  status: string;
  title: string;
  summary?: string | null;
  primaryAnchorKind?: string | null;
  primaryAnchorId?: string | null;
  primaryAnchorLineageId?: string | null;
  primaryAnchorKey?: string | null;
  createdByLabel?: string | null;
  messageCount?: number | null;
  lastMessageId?: string | null;
  lastMessageAt?: string | null;
  activeResponseMessageId?: string | null;
  contextDigest?: string | null;
  metadata?: unknown;
  createdAt: string;
  updatedAt: string;
  newsroomFeedKey?: string | null;
};

export type ConsoleChatMessage = {
  id: string;
  threadId?: string | null;
  parentMessageId?: string | null;
  sequenceNumber?: number | null;
  role?: string | null;
  messageKind?: string | null;
  messageType?: string | null;
  content?: string | null;
  summary?: string | null;
  responseStatus?: string | null;
  responseOwner?: string | null;
  responseStartedAt?: string | null;
  responseCompletedAt?: string | null;
  responseError?: string | null;
  source?: string | null;
  authorUserProfileId?: string | null;
  authorLabel?: string | null;
  metadata?: unknown;
  createdAt: string;
  updatedAt?: string | null;
};

type ConsoleMessageSubscriptionInput = {
  filter?: {
    threadId?: {
      eq?: string;
    };
  };
};

type ConsoleMessageSubscription = {
  unsubscribe: () => void;
};

type ConsoleMessageSubscriptionModel = {
  onCreate: (input?: ConsoleMessageSubscriptionInput) => {
    subscribe: (observer: {
      next: (value: unknown) => void;
      error?: (error: unknown) => void;
    }) => ConsoleMessageSubscription;
  };
  onUpdate: (input?: ConsoleMessageSubscriptionInput) => {
    subscribe: (observer: {
      next: (value: unknown) => void;
      error?: (error: unknown) => void;
    }) => ConsoleMessageSubscription;
  };
};

type GraphQLClient = {
  graphql: (options: {
    query: string;
    variables?: Record<string, unknown>;
    authMode?: typeof USER_POOL_AUTH_MODE;
  }) => Promise<{
    data?: Record<string, unknown> | null;
    errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
  }>;
};

function getGraphQLClient(): GraphQLClient {
  configureAmplifyClient();
  return generateClient<Schema>() as unknown as GraphQLClient;
}

function formatGraphQLError(error: { message?: string | null; errorType?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  if (!error) return "Unknown GraphQL error";
  return [error.errorType, error.message].filter(Boolean).join(": ") || "Unknown GraphQL error";
}

function assertGraphQL<T>(response: {
  data?: Record<string, unknown> | null;
  errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
}, field: string): T {
  const value = response.data?.[field];
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (value === undefined || value === null) {
    throw new Error(
      `Console chat API is unavailable (${field}). Regenerate amplify_outputs.json from the current backend or deploy the MessageThread schema.`,
    );
  }
  return value as T;
}

function readConnectionItems<T>(value: unknown): T[] {
  if (!value || typeof value !== "object") return [];
  const items = (value as { items?: unknown }).items;
  return Array.isArray(items) ? items as T[] : [];
}

function readConnectionNextToken(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const nextToken = (value as { nextToken?: unknown }).nextToken;
  return typeof nextToken === "string" && nextToken.trim() ? nextToken : null;
}

function truncateSummary(value: string | null): string | null {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  return normalized.length > 180 ? `${normalized.slice(0, 179)}…` : normalized;
}

async function maybeUploadConsoleMessageBody(messageId: string, content: string | null | undefined): Promise<void> {
  const text = String(content ?? "").trim();
  if (!text) return;
  await uploadModelPayloadForOwner({
    ownerKind: "message",
    ownerId: messageId,
    ownerLineageId: messageId,
    role: "message_body",
    sortKey: "message",
    filename: "message.md",
    mediaType: "text/markdown",
    content: text.endsWith("\n") ? text : `${text}\n`,
    status: "active",
  });
}

export async function listConsoleThreads(primaryAnchorKeyOrLimit: string | number = DEFAULT_CONSOLE_THREAD_ANCHOR_KEY, limit = 25): Promise<ConsoleChatThread[]> {
  const primaryAnchorKey =
    typeof primaryAnchorKeyOrLimit === "string" ? primaryAnchorKeyOrLimit : DEFAULT_CONSOLE_THREAD_ANCHOR_KEY;
  const resolvedLimit =
    typeof primaryAnchorKeyOrLimit === "number" ? primaryAnchorKeyOrLimit : limit;

  const threads = await listConsoleThreadsViaThreadModel(Math.max(resolvedLimit * 2, 100));
  return threads
    .filter((thread) => thread.threadKind === "console" && (thread.primaryAnchorKey ?? DEFAULT_CONSOLE_THREAD_ANCHOR_KEY) === primaryAnchorKey)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, resolvedLimit);
}

export async function listConsoleThreadByAnchor(primaryAnchorKey: string): Promise<ConsoleChatThread | null> {
  return (await listConsoleThreads(primaryAnchorKey, 1))[0] ?? null;
}

export async function listConsoleMessagesByThread(threadId: string): Promise<ConsoleChatMessage[]> {
  const messages = await listMessagesByThread(threadId, CONSOLE_MAX_MESSAGES);
  return messages.sort(
    (left, right) =>
      (left.sequenceNumber ?? 0) - (right.sequenceNumber ?? 0) ||
      left.createdAt.localeCompare(right.createdAt),
  );
}

export async function createConsoleThread(input: ConsoleChatThread): Promise<ConsoleChatThread> {
  const response = await getGraphQLClient().graphql({
    query: CREATE_CONSOLE_THREAD,
    variables: { input },
    authMode: USER_POOL_AUTH_MODE,
  });
  return assertGraphQL<ConsoleChatThread>(response, "createMessageThread");
}

export async function updateConsoleThread(input: Pick<ConsoleChatThread, "id"> & Partial<ConsoleChatThread>): Promise<ConsoleChatThread> {
  const response = await getGraphQLClient().graphql({
    query: UPDATE_CONSOLE_THREAD,
    variables: { input },
    authMode: USER_POOL_AUTH_MODE,
  });
  return assertGraphQL<ConsoleChatThread>(response, "updateMessageThread");
}

export type CreateConsoleMessageInput = ConsoleChatMessage & {
  messageDomain: string;
  status: string;
  source: string;
  authorLabel: string;
  semanticLayer: string;
  searchVisibility: string;
  responseTarget: string;
  metadata: string;
  updatedAt: string;
  newsroomFeedKey: string;
};

export async function createConsoleMessage(input: CreateConsoleMessageInput): Promise<ConsoleChatMessage> {
  // The backend stamps the author from the signed-in identity (postMessage): the browser names none and sets no timestamps.
  const args = postMessageArguments({ ...input, summary: input.summary ?? truncateSummary(input.content ?? null) } as unknown as Record<string, unknown>);
  const response = await getGraphQLClient().graphql({
    query: postMessageMutation(args, CONSOLE_MESSAGE_FIELDS),
    variables: args,
    authMode: USER_POOL_AUTH_MODE,
  });
  const created = normalizeConsoleMessageRecord(assertGraphQL<Record<string, unknown>>(response, "postMessage"));
  await maybeUploadConsoleMessageBody(created.id, input.content);
  if (messageHasHashtag(input.content)) {
    void getGraphQLClient()
      .graphql({ query: LINK_MESSAGE_HASHTAGS_MUTATION, variables: { messageId: created.id }, authMode: USER_POOL_AUTH_MODE })
      .catch(() => undefined);
  }
  return input.content?.trim() ? { ...created, content: input.content } : created;
}

export async function updateConsoleMessage(
  input: Pick<ConsoleChatMessage, "id"> & Partial<ConsoleChatMessage>,
): Promise<ConsoleChatMessage> {
  const normalizedInput: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined) normalizedInput[key] = value;
  }
  if (!normalizedInput.updatedAt) normalizedInput.updatedAt = new Date().toISOString();
  const response = await getGraphQLClient().graphql({
    query: UPDATE_CONSOLE_MESSAGE,
    variables: { input: normalizedInput },
    authMode: USER_POOL_AUTH_MODE,
  });
  return normalizeConsoleMessageRecord(assertGraphQL<Record<string, unknown>>(response, "updateMessage"));
}

export function subscribeConsoleMessages(
  threadId: string,
  onMessage: (message: ConsoleChatMessage) => void,
  onError?: (error: unknown) => void,
): () => void {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    models: {
      Message: ConsoleMessageSubscriptionModel;
    };
  };
  const messageModel = client.models.Message;
  const handleEvent = (value: unknown) => {
    const message = normalizeConsoleMessageSubscriptionPayload(value);
    if (!message) return;
    if (!message.threadId || message.threadId === threadId) onMessage(message);
  };
  const createSubscription = messageModel.onCreate().subscribe({ next: handleEvent, error: onError });
  const updateSubscription = messageModel.onUpdate().subscribe({ next: handleEvent, error: onError });
  return () => {
    createSubscription.unsubscribe();
    updateSubscription.unsubscribe();
  };
}

function normalizeConsoleMessageSubscriptionPayload(value: unknown): ConsoleChatMessage | null {
  const record = resolveConsoleMessageSubscriptionRecord(value);
  if (!record) return null;
  return normalizeConsoleMessageRecord(record);
}

function resolveConsoleMessageSubscriptionRecord(value: unknown): Record<string, unknown> | null {
  const queue: unknown[] = [value];
  const visited = new Set<unknown>();

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current || typeof current !== "object" || visited.has(current)) continue;
    visited.add(current);
    const record = current as Record<string, unknown>;
    if (typeof record.id === "string") return record;

    for (const [key, nested] of Object.entries(record)) {
      if (!nested || typeof nested !== "object") continue;
      if (
        key === "data"
        || key === "value"
        || key.startsWith("onCreate")
        || key.startsWith("onUpdate")
      ) {
        queue.push(nested);
      }
    }
  }

  return null;
}

async function listConsoleThreadsViaThreadModel(limit: number): Promise<ConsoleChatThread[]> {
  const pageSize = Math.min(Math.max(limit, 100), 500);
  const threads: ConsoleChatThread[] = [];
  let nextToken: string | null = null;

  do {
    const queryResult: { page: ConsoleChatThread[]; nextCursor: string | null } = await runConsoleReadQuery({
      query: LIST_CONSOLE_THREADS,
      variables: {
        limit: pageSize,
        nextToken,
      },
      map: (response) => {
        const connection = assertGraphQL<unknown>(response, "listMessageThreads");
        return {
          page: readConnectionItems<ConsoleChatThread>(connection),
          nextCursor: readConnectionNextToken(connection),
        };
      },
    });
    threads.push(...queryResult.page);
    nextToken = queryResult.nextCursor;
  } while (nextToken && threads.length < limit);

  return threads;
}

async function listMessagesByThread(threadId: string, maxMessages: number): Promise<ConsoleChatMessage[]> {
  const messages: ConsoleChatMessage[] = [];
  let nextToken: string | null = null;

  do {
    const queryResult: { page: ConsoleChatMessage[]; nextCursor: string | null } = await runConsoleReadQuery({
      query: LIST_CONSOLE_MESSAGES_BY_THREAD,
      variables: { threadId, limit: CONSOLE_PAGE_SIZE, nextToken },
      map: (response) => {
        const connection = assertGraphQL<unknown>(response, "listMessagesByThreadAndSequence");
        return {
          page: readConnectionItems<Record<string, unknown>>(connection).map(normalizeConsoleMessageRecord),
          nextCursor: readConnectionNextToken(connection),
        };
      },
    });
    messages.push(...queryResult.page);
    nextToken = queryResult.nextCursor;
  } while (nextToken && messages.length < maxMessages);

  return hydrateConsoleMessageBodies(messages);
}

async function hydrateConsoleMessageBodies(messages: ConsoleChatMessage[]): Promise<ConsoleChatMessage[]> {
  return Promise.all(messages.map(async (message) => {
    const payloads = await loadModelPayloadsForOwner("message", message.id, ["message_body"]);
    const body = payloads.find((payload) => payload.attachment.role === "message_body")?.text?.trim();
    return body ? { ...message, content: body } : message;
  }));
}

function normalizeConsoleMessageRecord(record: Record<string, unknown>): ConsoleChatMessage {
  const metadata = readJsonObject(record.metadata);
  const metadataConsole = readJsonObject(metadata?.console);
  const metadataConsoleAuthor = readJsonObject(metadataConsole?.author);
  const createdAt = readString(record.createdAt) ?? new Date().toISOString();
  const source = readString(record.source);
  const authorLabel = readString(record.authorLabel);
  const content = readString(record.content)
    ?? readString(record.body)
    ?? readString(metadata?.content)
    ?? null;
  const inferredRole = inferConsoleMessageRole(record, metadata);
  const threadId = readString(record.threadId)
    ?? readString(metadata?.threadId)
    ?? readString(metadata?.messageThreadId)
    ?? null;

  return {
    id: readString(record.id) ?? `message-unknown-${createdAt}`,
    threadId,
    parentMessageId: readString(record.parentMessageId) ?? readString(metadata?.parentMessageId) ?? null,
    sequenceNumber: readNumber(record.sequenceNumber) ?? readNumber(metadata?.sequenceNumber) ?? null,
    role: readString(record.role) ?? readString(metadata?.role) ?? inferredRole,
    messageKind: readString(record.messageKind) ?? null,
    messageType: readString(record.messageType) ?? readString(metadata?.messageType) ?? null,
    content,
    summary: readString(record.summary) ?? null,
    responseStatus: readString(record.responseStatus) ?? readString(metadata?.responseStatus) ?? null,
    responseOwner: readString(record.responseOwner) ?? readString(metadata?.responseOwner) ?? null,
    responseStartedAt: readString(record.responseStartedAt) ?? readString(metadata?.responseStartedAt) ?? null,
    responseCompletedAt: readString(record.responseCompletedAt) ?? readString(metadata?.responseCompletedAt) ?? null,
    responseError: readString(record.responseError) ?? readString(metadata?.responseError) ?? null,
    source,
    authorUserProfileId: (
      readString(record.authorUserProfileId)
      ?? readString(metadata?.authorUserProfileId)
      ?? readString(metadataConsoleAuthor?.userProfileId)
      ?? null
    ),
    authorLabel,
    metadata,
    createdAt,
    updatedAt: readString(record.updatedAt) ?? null,
  };
}

function inferConsoleMessageRole(
  record: Record<string, unknown>,
  metadata: Record<string, unknown> | null,
): string | null {
  const id = readString(record.id)?.toLowerCase() ?? "";
  if (id.startsWith("message-console-user-")) return "USER";
  if (id.startsWith("message-console-assistant-")) return "ASSISTANT";
  if (id.startsWith("message-console-tool-")) return "TOOL";

  const responseStatus = readString(record.responseStatus) ?? readString(metadata?.responseStatus);
  if (responseStatus === "PENDING") return "USER";
  if (responseStatus === "RUNNING" || responseStatus === "COMPLETED") return "ASSISTANT";

  const messageKind = readString(record.messageKind);
  if (messageKind === CONSOLE_TOOL_CALL_KIND || messageKind === CONSOLE_TOOL_RESULT_KIND) return "TOOL";

  const authorLabel = readString(record.authorLabel);
  const source = readString(record.source);
  if (authorLabel && source === "papyrus-console") return "USER";
  return null;
}

function readJsonObject(value: unknown): Record<string, unknown> | null {
  if (!value) return null;
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  return null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

async function runConsoleReadQuery<T>({
  query,
  variables,
  map,
}: {
  query: string;
  variables?: Record<string, unknown>;
  map: (response: {
    data?: Record<string, unknown> | null;
    errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
  }) => T;
}): Promise<T> {
  const response = await getGraphQLClient().graphql({ query, variables, authMode: USER_POOL_AUTH_MODE });
  return map(response);
}
