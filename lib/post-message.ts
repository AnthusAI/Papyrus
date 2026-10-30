/**
 * Messages are created through the `postMessage` mutation, never through `createMessage`: the backend stamps the author from the
 * signed-in identity, so a browser cannot name one. This is the one place that turns a Message record into that mutation and its
 * arguments, shared by the conversation, forum and console chat writers. Authorship and timestamps are left out on purpose.
 */

const ARGUMENT_TYPES = {
  id: "ID!",
  threadId: "ID!",
  content: "String",
  messageKind: "String!",
  messageDomain: "String!",
  summary: "String",
  parentMessageId: "ID",
  sequenceNumber: "Int",
  messageType: "String",
  role: "String",
  source: "String",
  authorLabel: "String",
  semanticLayer: "String",
  searchVisibility: "String",
  responseTarget: "String",
  responseStatus: "String",
  responseOwner: "String",
  responseStartedAt: "AWSDateTime",
  responseCompletedAt: "AWSDateTime",
  metadata: "AWSJSON",
  newsroomFeedKey: "String",
} as const;

export type PostMessageArguments = Partial<Record<keyof typeof ARGUMENT_TYPES, string | number | null>>;

type MessageLike = Record<string, unknown>;

/** The arguments of `postMessage` from a Message record. Anything else on the record (authorSub, authorUserProfileId, createdAt, updatedAt) is dropped. */
export function postMessageArguments(record: MessageLike): PostMessageArguments {
  const args: PostMessageArguments = {};
  for (const key of Object.keys(ARGUMENT_TYPES) as Array<keyof typeof ARGUMENT_TYPES>) {
    let value = record[key === "content" ? "content" : key];
    if (key === "content") value = record.content ?? record.body;
    if (value === undefined || value === null) continue;
    if (key === "metadata") value = typeof value === "string" ? value : JSON.stringify(value);
    args[key] = value as string | number;
  }
  return args;
}

/** `mutation PostMessage($id: ID!, …) { postMessage(id: $id, …) { <selection> } }` declaring exactly the arguments given. */
export function postMessageMutation(args: PostMessageArguments, selection: string): string {
  const keys = Object.keys(args) as Array<keyof typeof ARGUMENT_TYPES>;
  const declared = keys.map((key) => `$${key}: ${ARGUMENT_TYPES[key]}`).join(", ");
  const passed = keys.map((key) => `${key}: $${key}`).join(", ");
  return `mutation PostMessage(${declared}) { postMessage(${passed}) { ${selection} } }`;
}
