// postMessage: the only way a person's Message is created. The author is the signed-in user (the identity's sub), whatever the
// client sends: the mutation has no author argument, and a label is only a label. One DynamoDB PutItem that refuses to replace an
// existing Message (ids are derived from the sequence number, so a lost race comes back as a conflict the caller retries).
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

function clean(value) {
  const out = {};
  // The APPSYNC_JS runtime has no classic for loop and no ++; for...of is supported.
  for (const key of Object.keys(value)) {
    if (value[key] !== null && value[key] !== undefined) out[key] = value[key];
  }
  return out;
}

export function request(ctx) {
  const identity = ctx.identity;
  if (!identity || !identity.sub) util.error("Sign in to post a message.", "Unauthorized");
  const args = ctx.args;
  const content = typeof args.content === "string" ? args.content.trim() : "";
  // A placeholder waiting for a responder (PENDING) may start empty; any other message needs text.
  if (!content && args.responseStatus !== "PENDING") util.error("A message cannot be empty.", "BadRequest");
  if (!args.id || !args.threadId) util.error("A message needs an id and a conversation.", "BadRequest");
  const now = util.time.nowISO8601();
  const claims = identity.claims || {};
  const email = typeof claims.email === "string" ? claims.email : "";
  const label = typeof args.authorLabel === "string" && args.authorLabel.trim() ? args.authorLabel.trim() : email ? email : "editor";
  const item = clean({
    __typename: "Message",
    id: args.id,
    messageKind: args.messageKind,
    messageDomain: args.messageDomain,
    status: "active",
    summary: args.summary ? args.summary : content.slice(0, 120),
    source: args.source,
    authorSub: identity.sub,
    authorLabel: label,
    threadId: args.threadId,
    parentMessageId: args.parentMessageId,
    sequenceNumber: args.sequenceNumber,
    role: args.role ? args.role : "human",
    messageType: args.messageType,
    content: content,
    semanticLayer: args.semanticLayer,
    searchVisibility: args.searchVisibility,
    responseTarget: args.responseTarget,
    responseStatus: args.responseStatus ? args.responseStatus : "COMPLETED",
    responseOwner: args.responseOwner,
    responseStartedAt: args.responseStartedAt,
    responseCompletedAt: args.responseCompletedAt,
    metadata: args.metadata,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: args.newsroomFeedKey,
  });
  return ddb.put({ key: { id: args.id }, item: item, condition: { id: { attributeExists: false } } });
}

export function response(ctx) {
  if (ctx.error) {
    if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
      util.error("A message with this id already exists (conditional check failed); try again.", "Conflict");
    }
    util.error(ctx.error.message, ctx.error.type);
  }
  return ctx.result;
}
