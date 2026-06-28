"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { configureAmplifyClient } from "../components/amplify-client-provider";
import { loadModelPayloadsForOwner, uploadModelPayloadForOwner } from "../components/news-desk-taxonomy-client";

const USER_POOL_AUTH_MODE = "userPool";
const API_KEY_AUTH_MODE = "apiKey";
const DEFAULT_CONSOLE_THREAD_ANCHOR_KEY = "site#papyrus";
const CONSOLE_NEWSROOM_FEED_KEY = "consoleChat";
const CONSOLE_MESSAGE_KIND = "console_chat_turn";
const CONSOLE_MESSAGE_DOMAIN = "conversation";
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

const CONSOLE_MESSAGE_FIELDS_LEGACY = `
  id
  messageKind
  messageDomain
  summary
  source
  importRunId
  authorSub
  authorUserProfileId
  authorLabel
  createdAt
  updatedAt
  newsroomFeedKey
`;

const CONSOLE_MESSAGE_SELECTION_CANDIDATES = [
  "id",
  "threadId",
  "parentMessageId",
  "sequenceNumber",
  "role",
  "messageKind",
  "messageType",
  "content",
  "summary",
  "responseStatus",
  "responseOwner",
  "responseStartedAt",
  "responseCompletedAt",
  "responseError",
  "messageDomain",
  "source",
  "importRunId",
  "authorSub",
  "authorUserProfileId",
  "authorLabel",
  "newsroomFeedKey",
  "metadata",
  "body",
  "createdAt",
  "updatedAt",
] as const;

const CONSOLE_MESSAGE_REQUIRED_FIELDS = ["id", "createdAt", "updatedAt", "summary"] as const;

const CONSOLE_SCHEMA_INTROSPECTION = `
  query ConsoleChatSchemaIntrospection {
    queryType: __type(name: "Query") {
      fields {
        name
      }
    }
    messageType: __type(name: "Message") {
      fields {
        name
      }
    }
    createMessageInputType: __type(name: "CreateMessageInput") {
      inputFields {
        name
      }
    }
  }
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

const LIST_CONSOLE_MESSAGES_LEGACY = `
  query ListMessages(
    $limit: Int
    $nextToken: String
  ) {
    listMessages(
      limit: $limit
      nextToken: $nextToken
    ) {
      items {
        ${CONSOLE_MESSAGE_FIELDS_LEGACY}
      }
      nextToken
    }
  }
`;

const LIST_CONSOLE_MESSAGES_BY_FEED_LEGACY = `
  query ListMessagesByNewsroomFeedAndCreatedAt(
    $newsroomFeedKey: String!
    $limit: Int
    $nextToken: String
  ) {
    listMessagesByNewsroomFeedAndCreatedAt(
      newsroomFeedKey: $newsroomFeedKey
      limit: $limit
      nextToken: $nextToken
    ) {
      items {
        ${CONSOLE_MESSAGE_FIELDS_LEGACY}
      }
      nextToken
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

const CREATE_CONSOLE_MESSAGE_LEGACY = `
  mutation CreateMessage($input: CreateMessageInput!) {
    createMessage(input: $input) {
      ${CONSOLE_MESSAGE_FIELDS_LEGACY}
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
    authMode?: typeof USER_POOL_AUTH_MODE | typeof API_KEY_AUTH_MODE;
  }) => Promise<{
    data?: Record<string, unknown> | null;
    errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
  }>;
};

type ConsoleSchemaSnapshot = {
  queryFields: Set<string>;
  messageFields: Set<string>;
  createMessageInputFields: Set<string>;
};

let consoleSchemaSnapshot: ConsoleSchemaSnapshot | null = null;
let consoleSchemaSnapshotPromise: Promise<ConsoleSchemaSnapshot> | null = null;

function getGraphQLClient(): GraphQLClient {
  configureAmplifyClient();
  return generateClient<Schema>() as unknown as GraphQLClient;
}

async function runGraphQLWithAuthModes(options: {
  query: string;
  variables?: Record<string, unknown>;
}): Promise<{
  data?: Record<string, unknown> | null;
  errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
}> {
  const client = getGraphQLClient();
  try {
    return await client.graphql({
      query: options.query,
      variables: options.variables,
      authMode: USER_POOL_AUTH_MODE,
    });
  } catch (firstError) {
    try {
      return await client.graphql({
        query: options.query,
        variables: options.variables,
        authMode: API_KEY_AUTH_MODE,
      });
    } catch (secondError) {
      throw normalizeUnknownError(secondError, "graphql", firstError);
    }
  }
}

function formatGraphQLError(error: { message?: string | null; errorType?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  if (!error) return "Unknown GraphQL error";
  return [error.errorType, error.message].filter(Boolean).join(": ") || "Unknown GraphQL error";
}

function assertGraphQL<T>(response: {
  data?: Record<string, unknown> | null;
  errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
}, field: string, options?: { allowPartialData?: boolean }): T {
  const value = response.data?.[field];
  if (response.errors?.length) {
    if (options?.allowPartialData && value !== undefined && value !== null) {
      return value as T;
    }
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

function readNameSet(value: unknown): Set<string> {
  const names = new Set<string>();
  if (!value || typeof value !== "object") return names;
  const fields = (value as { fields?: unknown; inputFields?: unknown }).fields
    ?? (value as { inputFields?: unknown }).inputFields;
  if (!Array.isArray(fields)) return names;
  for (const field of fields) {
    if (!field || typeof field !== "object") continue;
    const name = (field as { name?: unknown }).name;
    if (typeof name === "string" && name.trim()) names.add(name.trim());
  }
  return names;
}

function chooseMessageSelectionSet(schemaFields: Set<string> | null): string {
  if (!schemaFields || !schemaFields.size) return CONSOLE_MESSAGE_FIELDS;
  const selected = CONSOLE_MESSAGE_SELECTION_CANDIDATES.filter((field) => schemaFields.has(field));
  for (const field of CONSOLE_MESSAGE_REQUIRED_FIELDS) {
    if (schemaFields.has(field) && !selected.includes(field)) selected.push(field);
  }
  if (!selected.includes("id")) selected.unshift("id");
  return selected.join("\n  ");
}

function fieldValuesForCreateMessageInput(input: CreateConsoleMessageInput): Record<string, unknown> {
  return {
    id: input.id,
    messageKind: input.messageKind,
    messageDomain: input.messageDomain,
    status: input.status,
    summary: input.summary ?? truncateSummary(input.content ?? null),
    source: input.source,
    importRunId: null,
    authorSub: null,
    authorUserProfileId: input.authorUserProfileId ?? null,
    authorLabel: input.authorLabel,
    threadId: input.threadId ?? null,
    parentMessageId: input.parentMessageId ?? null,
    sequenceNumber: input.sequenceNumber ?? null,
    role: input.role ?? null,
    messageType: input.messageType ?? null,
    semanticLayer: input.semanticLayer,
    searchVisibility: input.searchVisibility,
    responseTarget: input.responseTarget,
    responseStatus: input.responseStatus ?? null,
    responseOwner: input.responseOwner ?? null,
    responseStartedAt: input.responseStartedAt ?? null,
    responseCompletedAt: input.responseCompletedAt ?? null,
    responseError: input.responseError ?? null,
    metadata: input.metadata,
    createdAt: input.createdAt,
    updatedAt: input.updatedAt,
    newsroomFeedKey: input.newsroomFeedKey,
  };
}

function buildCreateMessageInputCandidates(
  input: CreateConsoleMessageInput,
  availableFields: Set<string>,
): Record<string, unknown>[] {
  const values = fieldValuesForCreateMessageInput(input);
  const candidates: Record<string, unknown>[] = [];
  const seen = new Set<string>();

  const pushCandidate = (candidate: Record<string, unknown>) => {
    const cleaned: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(candidate)) {
      if (value !== undefined) cleaned[key] = value;
    }
    const signature = JSON.stringify(Object.keys(cleaned).sort().map((key) => [key, cleaned[key]]));
    if (!seen.has(signature)) {
      seen.add(signature);
      candidates.push(cleaned);
    }
  };

  if (availableFields.size) {
    pushCandidate(sanitizeCreateMessageInput(input, availableFields));
  } else {
    pushCandidate(values);
    pushCandidate({
      id: values.id,
      messageKind: values.messageKind,
      messageDomain: values.messageDomain,
      status: values.status,
      summary: values.summary,
      source: values.source,
      authorLabel: values.authorLabel,
      createdAt: values.createdAt,
      updatedAt: values.updatedAt,
      newsroomFeedKey: values.newsroomFeedKey,
    });
  }

  return candidates;
}

async function loadConsoleSchemaSnapshot(): Promise<ConsoleSchemaSnapshot> {
  if (consoleSchemaSnapshot) return consoleSchemaSnapshot;
  if (consoleSchemaSnapshotPromise) return consoleSchemaSnapshotPromise;
  consoleSchemaSnapshotPromise = (async () => {
    try {
      const response = await runGraphQLWithAuthModes({
        query: CONSOLE_SCHEMA_INTROSPECTION,
      });
      if (response.errors?.length) throw new Error(response.errors.map(formatGraphQLError).join("; "));
      const data = response.data ?? {};
      const snapshot: ConsoleSchemaSnapshot = {
        queryFields: readNameSet(data.queryType),
        messageFields: readNameSet(data.messageType),
        createMessageInputFields: readNameSet(data.createMessageInputType),
      };
      consoleSchemaSnapshot = snapshot;
      return snapshot;
    } catch {
      const snapshot: ConsoleSchemaSnapshot = {
        queryFields: new Set<string>(),
        messageFields: new Set<string>(),
        createMessageInputFields: new Set<string>(),
      };
      consoleSchemaSnapshot = snapshot;
      return snapshot;
    } finally {
      consoleSchemaSnapshotPromise = null;
    }
  })();
  return consoleSchemaSnapshotPromise;
}

function buildListMessagesQuery(
  field: "listMessages" | "listMessagesByNewsroomFeedAndCreatedAt" | "listMessagesByKindAndCreatedAt" | "listMessagesByDomainAndCreatedAt",
  selectionSet: string,
): string {
  if (field === "listMessages") {
    return `
      query ListMessages($limit: Int, $nextToken: String) {
        listMessages(limit: $limit, nextToken: $nextToken) {
          items {
            ${selectionSet}
          }
          nextToken
        }
      }
    `;
  }
  if (field === "listMessagesByNewsroomFeedAndCreatedAt") {
    return `
      query ListMessagesByNewsroomFeedAndCreatedAt($newsroomFeedKey: String!, $limit: Int, $nextToken: String) {
        listMessagesByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, limit: $limit, nextToken: $nextToken) {
          items {
            ${selectionSet}
          }
          nextToken
        }
      }
    `;
  }
  if (field === "listMessagesByKindAndCreatedAt") {
    return `
      query ListMessagesByKindAndCreatedAt($messageKind: String!, $limit: Int, $nextToken: String) {
        listMessagesByKindAndCreatedAt(messageKind: $messageKind, limit: $limit, nextToken: $nextToken) {
          items {
            ${selectionSet}
          }
          nextToken
        }
      }
    `;
  }
  return `
    query ListMessagesByDomainAndCreatedAt($messageDomain: String!, $limit: Int, $nextToken: String) {
      listMessagesByDomainAndCreatedAt(messageDomain: $messageDomain, limit: $limit, nextToken: $nextToken) {
        items {
          ${selectionSet}
        }
        nextToken
      }
    }
  `;
}

function sanitizeCreateMessageInput(
  input: CreateConsoleMessageInput,
  availableFields: Set<string>,
): Record<string, unknown> {
  const fieldValues: Record<string, unknown> = {
    id: input.id,
    messageKind: input.messageKind,
    messageDomain: input.messageDomain,
    status: input.status,
    summary: input.summary ?? truncateSummary(input.content ?? null),
    source: input.source,
    importRunId: null,
    authorSub: null,
    authorUserProfileId: input.authorUserProfileId ?? null,
    authorLabel: input.authorLabel,
    threadId: input.threadId ?? null,
    parentMessageId: input.parentMessageId ?? null,
    sequenceNumber: input.sequenceNumber ?? null,
    role: input.role ?? null,
    messageType: input.messageType ?? null,
    semanticLayer: input.semanticLayer,
    searchVisibility: input.searchVisibility,
    responseTarget: input.responseTarget,
    responseStatus: input.responseStatus ?? null,
    responseOwner: input.responseOwner ?? null,
    responseStartedAt: input.responseStartedAt ?? null,
    responseCompletedAt: input.responseCompletedAt ?? null,
    responseError: input.responseError ?? null,
    metadata: input.metadata,
    createdAt: input.createdAt,
    updatedAt: input.updatedAt,
    newsroomFeedKey: input.newsroomFeedKey,
  };

  if (!availableFields.size) {
    const conservativeFields = [
      "id",
      "messageKind",
      "messageDomain",
      "status",
      "summary",
      "source",
      "authorLabel",
      "createdAt",
      "updatedAt",
      "newsroomFeedKey",
    ] as const;
    const conservative: Record<string, unknown> = {};
    for (const key of conservativeFields) {
      const value = fieldValues[key];
      if (value !== undefined) conservative[key] = value;
    }
    return conservative;
  }

  const sanitized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(fieldValues)) {
    if (!availableFields.has(key)) continue;
    if (value === undefined) continue;
    sanitized[key] = value;
  }
  return sanitized;
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

  try {
    const maxThreads = Math.max(resolvedLimit * 2, 100);
    const threads = await listConsoleThreadsViaThreadModel(maxThreads);
    return threads
      .filter((thread) => thread.threadKind === "console" && (thread.primaryAnchorKey ?? DEFAULT_CONSOLE_THREAD_ANCHOR_KEY) === primaryAnchorKey)
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
      .slice(0, resolvedLimit);
  } catch (error) {
    if (!isUnavailableQueryError(error)) throw error;
    const messages = await listConsoleMessagesRaw(Math.max(resolvedLimit * 20, 500), 5000);
    return deriveConsoleThreadsFromMessages(messages, primaryAnchorKey).slice(0, resolvedLimit);
  }
}

export async function listConsoleThreadByAnchor(primaryAnchorKey: string): Promise<ConsoleChatThread | null> {
  return (await listConsoleThreads(primaryAnchorKey, 1))[0] ?? null;
}

export async function listConsoleMessagesByThread(threadId: string): Promise<ConsoleChatMessage[]> {
  const messages = await listConsoleMessagesRaw(300, 5000);
  const hasExplicitThreadIds = messages.some((message) => typeof message.threadId === "string" && message.threadId.trim());
  const scoped = hasExplicitThreadIds
    ? messages.filter((message) => message.threadId === threadId)
    : messages;
  return scoped.sort(
    (left, right) =>
      (left.sequenceNumber ?? 0) - (right.sequenceNumber ?? 0) ||
      left.createdAt.localeCompare(right.createdAt),
  );
}

export async function createConsoleThread(input: ConsoleChatThread): Promise<ConsoleChatThread> {
  try {
    const response = await getGraphQLClient().graphql({
      query: CREATE_CONSOLE_THREAD,
      variables: { input },
      authMode: USER_POOL_AUTH_MODE,
    });
    return assertGraphQL<ConsoleChatThread>(response, "createMessageThread");
  } catch (error) {
    if (isUnavailableQueryError(error)) return input;
    throw normalizeUnknownError(error, "createMessageThread");
  }
}

export async function updateConsoleThread(input: Pick<ConsoleChatThread, "id"> & Partial<ConsoleChatThread>): Promise<ConsoleChatThread> {
  try {
    const response = await getGraphQLClient().graphql({
      query: UPDATE_CONSOLE_THREAD,
      variables: { input },
      authMode: USER_POOL_AUTH_MODE,
    });
    return assertGraphQL<ConsoleChatThread>(response, "updateMessageThread");
  } catch (error) {
    if (isUnavailableQueryError(error)) {
      const now = new Date().toISOString();
      return {
        id: input.id,
        threadKind: input.threadKind ?? "console",
        status: input.status ?? "active",
        title: input.title ?? "Papyrus Console",
        summary: input.summary ?? null,
        primaryAnchorKind: input.primaryAnchorKind ?? "site",
        primaryAnchorId: input.primaryAnchorId ?? "papyrus",
        primaryAnchorLineageId: input.primaryAnchorLineageId ?? "papyrus",
        primaryAnchorKey: input.primaryAnchorKey ?? DEFAULT_CONSOLE_THREAD_ANCHOR_KEY,
        createdByLabel: input.createdByLabel ?? null,
        messageCount: input.messageCount ?? null,
        lastMessageId: input.lastMessageId ?? null,
        lastMessageAt: input.lastMessageAt ?? null,
        activeResponseMessageId: input.activeResponseMessageId ?? null,
        contextDigest: input.contextDigest ?? null,
        metadata: input.metadata ?? null,
        createdAt: input.createdAt ?? now,
        updatedAt: input.updatedAt ?? now,
        newsroomFeedKey: input.newsroomFeedKey ?? CONSOLE_NEWSROOM_FEED_KEY,
      };
    }
    throw normalizeUnknownError(error, "updateMessageThread");
  }
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
  const snapshot = await loadConsoleSchemaSnapshot();
  const selectionSets = snapshot.messageFields.size
    ? [chooseMessageSelectionSet(snapshot.messageFields)]
    : [CONSOLE_MESSAGE_FIELDS, CONSOLE_MESSAGE_FIELDS_LEGACY];
  const inputCandidates = buildCreateMessageInputCandidates(input, snapshot.createMessageInputFields);
  let lastError: unknown = null;

  for (const selectionSet of selectionSets) {
    const createMutation = `
      mutation CreateMessage($input: CreateMessageInput!) {
        createMessage(input: $input) {
          ${selectionSet}
        }
      }
    `;
    for (const candidateInput of inputCandidates) {
      try {
        const response = await getGraphQLClient().graphql({
          query: createMutation,
          variables: { input: candidateInput },
          authMode: USER_POOL_AUTH_MODE,
        });
        const created = normalizeConsoleMessageRecord(assertGraphQL<Record<string, unknown>>(response, "createMessage"));
        await maybeUploadConsoleMessageBody(created.id, input.content);
        return input.content?.trim() ? { ...created, content: input.content } : created;
      } catch (error) {
        if (!isUnavailableQueryError(error)) throw normalizeUnknownError(error, "createMessage");
        lastError = error;
      }
    }
  }

  if (lastError) {
    try {
      const response = await getGraphQLClient().graphql({
        query: CREATE_CONSOLE_MESSAGE_LEGACY,
        variables: {
          input: inputCandidates[inputCandidates.length - 1] ?? {},
        },
        authMode: USER_POOL_AUTH_MODE,
      });
      const created = normalizeConsoleMessageRecord(assertGraphQL<Record<string, unknown>>(response, "createMessage"));
      await maybeUploadConsoleMessageBody(created.id, input.content);
      return input.content?.trim() ? { ...created, content: input.content } : created;
    } catch (error) {
      if (!isUnavailableQueryError(error)) throw normalizeUnknownError(error, "createMessage");
      lastError = error;
    }
  }

  throw normalizeUnknownError(lastError, "createMessage");
}

export async function updateConsoleMessage(
  input: Pick<ConsoleChatMessage, "id"> & Partial<ConsoleChatMessage>,
): Promise<ConsoleChatMessage> {
  const now = new Date().toISOString();
  const normalizedInput: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined) normalizedInput[key] = value;
  }
  if (!normalizedInput.updatedAt) normalizedInput.updatedAt = now;
  const snapshot = await loadConsoleSchemaSnapshot();
  const selectionSets = snapshot.messageFields.size
    ? [chooseMessageSelectionSet(snapshot.messageFields)]
    : [CONSOLE_MESSAGE_FIELDS, CONSOLE_MESSAGE_FIELDS_LEGACY];
  let lastError: unknown = null;

  for (const selectionSet of selectionSets) {
    const updateMutation = `
      mutation UpdateMessage($input: UpdateMessageInput!) {
        updateMessage(input: $input) {
          ${selectionSet}
        }
      }
    `;
    try {
      const response = await getGraphQLClient().graphql({
        query: updateMutation,
        variables: { input: normalizedInput },
        authMode: USER_POOL_AUTH_MODE,
      });
      return normalizeConsoleMessageRecord(assertGraphQL<Record<string, unknown>>(response, "updateMessage"));
    } catch (error) {
      if (!isUnavailableQueryError(error)) throw normalizeUnknownError(error, "updateMessage");
      lastError = error;
    }
  }

  throw normalizeUnknownError(lastError, "updateMessage");
}

export function subscribeConsoleMessages(
  threadId: string,
  onMessage: (message: ConsoleChatMessage) => void,
  onError?: (error: unknown) => void,
): () => void {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    models: {
      Message?: ConsoleMessageSubscriptionModel;
    };
  };
  const messageModel = client.models.Message;
  if (!messageModel || typeof messageModel.onCreate !== "function" || typeof messageModel.onUpdate !== "function") {
    return () => undefined;
  }
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
      field: "listMessageThreads",
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

async function listConsoleMessagesRaw(pageSize: number, maxMessages: number): Promise<ConsoleChatMessage[]> {
  const schema = await loadConsoleSchemaSnapshot();
  const selectionSets = schema.messageFields.size
    ? [chooseMessageSelectionSet(schema.messageFields)]
    : [CONSOLE_MESSAGE_FIELDS, CONSOLE_MESSAGE_FIELDS_LEGACY];
  const attempts: Array<{
    field: string;
    query: string;
    variables: Record<string, unknown>;
    messageKinds?: string[];
  }> = [];

  const addDynamicAttempt = (
    field: "listMessagesByNewsroomFeedAndCreatedAt" | "listMessagesByKindAndCreatedAt" | "listMessagesByDomainAndCreatedAt" | "listMessages",
    selectionSet: string,
    variables: Record<string, unknown>,
  ) => {
    if (schema.queryFields.size > 0 && !schema.queryFields.has(field)) return;
    attempts.push({
      field,
      query: buildListMessagesQuery(field, selectionSet),
      variables,
    });
  };

  for (const selectionSet of selectionSets) {
    addDynamicAttempt("listMessagesByNewsroomFeedAndCreatedAt", selectionSet, {
      newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
      limit: pageSize,
    });

    if (schema.queryFields.size === 0 || schema.queryFields.has("listMessagesByKindAndCreatedAt")) {
      attempts.push({
        field: "listMessagesByKindAndCreatedAt",
        query: buildListMessagesQuery("listMessagesByKindAndCreatedAt", selectionSet),
        variables: { limit: pageSize },
        messageKinds: [CONSOLE_MESSAGE_KIND, CONSOLE_TOOL_CALL_KIND, CONSOLE_TOOL_RESULT_KIND],
      });
    }

    addDynamicAttempt("listMessagesByDomainAndCreatedAt", selectionSet, {
      messageDomain: CONSOLE_MESSAGE_DOMAIN,
      limit: pageSize,
    });

    addDynamicAttempt("listMessages", selectionSet, {
      limit: pageSize,
    });
  }

  if (!attempts.length) {
    attempts.push(
      {
        field: "listMessagesByNewsroomFeedAndCreatedAt",
        query: LIST_CONSOLE_MESSAGES_BY_FEED_LEGACY,
        variables: { newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY, limit: pageSize },
      },
      {
        field: "listMessages",
        query: LIST_CONSOLE_MESSAGES_LEGACY,
        variables: { limit: pageSize },
      },
    );
  }

  let lastError: unknown = null;
  for (const attempt of attempts) {
    try {
      if (attempt.messageKinds?.length && attempt.field === "listMessagesByKindAndCreatedAt") {
        return await listMessagesByKindsWithQuery(
          attempt.field,
          attempt.query,
          attempt.variables,
          attempt.messageKinds,
          maxMessages,
        );
      }
      return await listMessagesWithQuery(attempt.field, attempt.query, attempt.variables, maxMessages);
    } catch (error) {
      if (!isUnavailableQueryError(error)) throw error;
      lastError = error;
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Console chat listMessages failed: no compatible query shape.");
}

async function listMessagesByKindsWithQuery(
  field: string,
  query: string,
  baseVariables: Record<string, unknown>,
  messageKinds: string[],
  maxMessages: number,
): Promise<ConsoleChatMessage[]> {
  const byId = new Map<string, ConsoleChatMessage>();
  for (const messageKind of messageKinds) {
    const page = await listMessagesWithQuery(field, query, { ...baseVariables, messageKind }, maxMessages);
    for (const message of page) {
      byId.set(message.id, message);
    }
  }
  return [...byId.values()].sort(
    (left, right) =>
      (left.sequenceNumber ?? 0) - (right.sequenceNumber ?? 0) ||
      left.createdAt.localeCompare(right.createdAt),
  );
}

async function listMessagesWithQuery(
  field: string,
  query: string,
  baseVariables: Record<string, unknown>,
  maxMessages: number,
): Promise<ConsoleChatMessage[]> {
  const messages: ConsoleChatMessage[] = [];
  let nextToken: string | null = null;

  do {
    const queryResult: { page: ConsoleChatMessage[]; nextCursor: string | null } = await runConsoleReadQuery({
      field,
      query,
      variables: {
        ...baseVariables,
        nextToken,
      },
      map: (response) => {
        const connection = assertGraphQL<unknown>(response, field, { allowPartialData: true });
        const items = readConnectionItems<Record<string, unknown> | null>(connection)
          .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
          .map(normalizeConsoleMessageRecord);
        return {
          page: items,
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
    try {
      const payloads = await loadModelPayloadsForOwner("message", message.id, ["message_body"]);
      const body = payloads.find((payload) => payload.attachment.role === "message_body")?.text?.trim();
      if (body) return { ...message, content: body };
    } catch {
      // Fall back to inline field.
    }
    return message;
  }));
}

function deriveConsoleThreadsFromMessages(messages: ConsoleChatMessage[], primaryAnchorKey: string): ConsoleChatThread[] {
  const threadlessMessages = messages.filter((message) => message.messageKind === CONSOLE_MESSAGE_KIND || !message.messageKind);
  const hasThreadIds = threadlessMessages.some((message) => message.threadId?.trim());
  if (!hasThreadIds) {
    if (!threadlessMessages.length) return [];
    const ordered = [...threadlessMessages].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
    const first = ordered[0];
    const last = ordered[ordered.length - 1];
    return [{
      id: "message-thread-console-default",
      threadKind: "console",
      status: "active",
      title: "Papyrus Console",
      summary: last.summary ?? last.content ?? null,
      primaryAnchorKind: "site",
      primaryAnchorId: "papyrus",
      primaryAnchorLineageId: "papyrus",
      primaryAnchorKey: primaryAnchorKey,
      createdByLabel: null,
      messageCount: ordered.length,
      lastMessageId: last.id,
      lastMessageAt: last.createdAt,
      contextDigest: null,
      metadata: null,
      createdAt: first.createdAt,
      updatedAt: last.createdAt,
      newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
    }];
  }

  const byThread = new Map<string, {
    count: number;
    firstCreatedAt: string;
    lastCreatedAt: string;
    lastMessageId: string;
    summary: string | null;
  }>();

  for (const message of messages) {
    const threadId = message.threadId?.trim();
    if (!threadId) continue;
    if (message.messageKind && message.messageKind !== CONSOLE_MESSAGE_KIND) continue;
    const createdAt = message.createdAt ?? message.updatedAt ?? new Date().toISOString();
    const existing = byThread.get(threadId);
    if (!existing) {
      byThread.set(threadId, {
        count: 1,
        firstCreatedAt: createdAt,
        lastCreatedAt: createdAt,
        lastMessageId: message.id,
        summary: (message.summary ?? message.content ?? null),
      });
      continue;
    }
    existing.count += 1;
    if (createdAt < existing.firstCreatedAt) existing.firstCreatedAt = createdAt;
    if (createdAt >= existing.lastCreatedAt) {
      existing.lastCreatedAt = createdAt;
      existing.lastMessageId = message.id;
      existing.summary = (message.summary ?? message.content ?? existing.summary);
    }
  }

  return [...byThread.entries()]
    .map(([threadId, value]) => ({
      id: threadId,
      threadKind: "console",
      status: "active",
      title: "Papyrus Console",
      summary: value.summary,
      primaryAnchorKind: "site",
      primaryAnchorId: "papyrus",
      primaryAnchorLineageId: "papyrus",
      primaryAnchorKey: primaryAnchorKey,
      createdByLabel: null,
      messageCount: value.count,
      lastMessageId: value.lastMessageId,
      lastMessageAt: value.lastCreatedAt,
      contextDigest: null,
      metadata: null,
      createdAt: value.firstCreatedAt,
      updatedAt: value.lastCreatedAt,
      newsroomFeedKey: CONSOLE_NEWSROOM_FEED_KEY,
    }))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

function isUnavailableQueryError(error: unknown): boolean {
  const text = (stringifyUnknownError(error) ?? "").toLowerCase();
  if (!text) return false;
  return (
    text.includes("unauthorized") ||
    text.includes("not authorized") ||
    text.includes("access denied") ||
    text.includes("fieldundefined") ||
    text.includes("cannot query field") ||
    text.includes("unknown type") ||
    text.includes("unknowntype") ||
    text.includes("validation error of type") ||
    text.includes("is not defined for input object type")
  );
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
  field,
  map,
}: {
  query: string;
  variables?: Record<string, unknown>;
  field: string;
  map: (response: {
    data?: Record<string, unknown> | null;
    errors?: Array<{ message?: string | null; errorType?: string | null } | string | null> | null;
  }) => T;
}): Promise<T> {
  const client = getGraphQLClient();
  try {
    const response = await client.graphql({
      query,
      variables,
      authMode: USER_POOL_AUTH_MODE,
    });
    return map(response);
  } catch (firstError) {
    try {
      const response = await client.graphql({
        query,
        variables,
        authMode: API_KEY_AUTH_MODE,
      });
      return map(response);
    } catch (secondError) {
      throw normalizeUnknownError(secondError, field, firstError);
    }
  }
}

function normalizeUnknownError(error: unknown, operation: string, fallback?: unknown): Error {
  if (error instanceof Error && error.message.trim()) return error;
  const primary = stringifyUnknownError(error);
  const secondary = stringifyUnknownError(fallback);
  const details = [primary, secondary].filter(Boolean).join(" | ");
  return new Error(details ? `Console chat ${operation} failed: ${details}` : `Console chat ${operation} failed.`);
}

function stringifyUnknownError(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message || error.name;
  try {
    const text = JSON.stringify(error);
    return text && text !== "{}" ? text : Object.prototype.toString.call(error);
  } catch {
    return Object.prototype.toString.call(error);
  }
}
