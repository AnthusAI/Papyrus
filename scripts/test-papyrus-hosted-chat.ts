import assert from "node:assert/strict";
import { GetItemCommand, PutItemCommand, QueryCommand, UpdateItemCommand } from "@aws-sdk/client-dynamodb";
import type { NextRequest } from "next/server";
import { derivePapyrusChatScope, handlePapyrusHostedChatRequest } from "../lib/papyrus-hosted-chat";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";
import { ProspectusAccountsError } from "../lib/prospectus-site-identity";

const secret = "papyrus-hosted-chat-test-sealing-secret-32-bytes-minimum";
const siteProduct = "papyrus-demo";
const accountId = "publishing-account-1";
const now = 1_798_000_000;
const environment = { PAPYRUS_SITE_ORIGIN: "https://papyrus.example", NODE_ENV: "test" };

function requestFor(method: string, personId: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  const expiresAt = now + 600;
  const session = sealProspectusCookie(secret, PROSPECTUS_SESSION_COOKIE, {
    personId,
    accessToken: `access-${personId}`,
    accessTokenExpiresAt: expiresAt,
    selectedAccountId: accountId,
  }, expiresAt);
  return withNextRequestShape(new Request(`https://papyrus.example/api/newsroom/chat/${path}`, {
    method,
    headers: {
      cookie: `${PROSPECTUS_SESSION_COOKIE}=${session}`,
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...headers,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }));
}

function withNextRequestShape(request: Request) {
  const cookieHeader = request.headers.get("cookie") ?? "";
  const cookies = new Map(cookieHeader.split(";").map((part) => part.trim().split(/=(.*)/s).slice(0, 2) as [string, string]));
  Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
  Object.defineProperty(request, "cookies", { value: { get(name: string) { const value = cookies.get(name); return value === undefined ? undefined : { value }; } } });
  return request as unknown as NextRequest;
}

function prospectusRuntime() {
  const authorizationCalls: Array<{ personId: string; accountId: string; operation: string }> = [];
  const accounts = {
    async accountDirectory(accessToken: string) {
      const personId = accessToken.replace("access-", "");
      return {
        person: { id: personId },
        accounts: [{ id: accountId, name: "Newsroom", role: "member", products: [{ product: siteProduct, status: "active" }] }],
      };
    },
    async currentPerson(accessToken: string) { return { person: { id: accessToken.replace("access-", "") } }; },
    async authorizeAccountOperation(accessToken: string, requestedAccountId: string, operation: string) {
      const personId = accessToken.replace("access-", "");
      authorizationCalls.push({ personId, accountId: requestedAccountId, operation });
      if (personId === "denied-editor") throw new ProspectusAccountsError(403, "not_authorized", "not authorized");
      return { allowed: true, personId, accountId: requestedAccountId, operation, product: siteProduct, role: "member", revision: 1 };
    },
  };
  return {
    authorizationCalls,
    runtime: { sealingSecret: secret, accounts: accounts as never, cognitoClient: {} as never },
  };
}

function fakeDynamo() {
  const items = new Map<string, Record<string, { S?: string; N?: string }>>();
  let nextSequence = 1;
  return {
    items,
    client: {
      async send(command: { constructor: { name: string }; input: Record<string, any> }): Promise<any> {
        if (command.constructor.name === UpdateItemCommand.name) {
          nextSequence += 1;
          return { Attributes: { next_seq: { N: String(nextSequence) } } };
        }
        if (command.constructor.name === PutItemCommand.name) {
          const item = command.input.Item as Record<string, { S?: string; N?: string }>;
          items.set(`${item.pk?.S}\0${item.sk?.S}`, item);
          return {};
        }
        if (command.constructor.name === QueryCommand.name) {
          const partition = command.input.ExpressionAttributeValues?.[":pk"]?.S;
          return { Items: [...items.values()].filter((item) => item.pk?.S === partition) };
        }
        if (command.constructor.name === GetItemCommand.name) return {};
        throw new Error(`Unexpected test DynamoDB command: ${command.constructor.name}`);
      },
    },
  };
}

function coreDependencies() {
  const scope = derivePapyrusChatScope(siteProduct, accountId, "editor-a");
  const channelId = "private-channel-a";
  const messages: any[] = [];
  const completed = new Map<string, { message: any; turnId: string | null }>();
  const store = {
    async getChannel(tenantId: string, requestedChannelId: string) {
      if (tenantId !== scope.tenantId || requestedChannelId !== channelId) return null;
      return {
        channelId, tenantId: scope.tenantId, kind: "direct", name: null,
        participants: [
          { kind: "human", actorId: scope.editorId },
          { kind: "bot", actorId: "editorial-assistant" },
        ], nextSeq: 1,
      };
    },
    async reservePostIdempotency(_tenantId: string, key: string, _fingerprint: string, candidate: any) {
      const prior = completed.get(key);
      if (prior) return { state: "completed", result: prior };
      return { state: "owner", reservation: { ...candidate, seq: null, admission: null } };
    },
    async setPostIdempotencySequence(_tenantId: string, _key: string, _owner: string, seq: number) { return seq; },
    async completePostIdempotency(_tenantId: string, key: string, _owner: string, message: any, turnId: string | null) {
      completed.set(key, { message, turnId });
      messages.push(message);
      return true;
    },
  };
  const dynamo = fakeDynamo();
  const turn = {
    turnId: "private-turn-a", tenantId: scope.tenantId, channelId, botId: "editorial-assistant", status: "completed",
    promptMessageSeq: null, promptAuthorId: scope.editorId, attemptId: null, attempt: 0, claimedBy: null,
    leaseExpiresAt: null, deadlineAt: null, recoveryAttempts: 0, waitingFor: null, waitingSince: null,
    logicalEnqueueIds: [], pendingComputerTool: null, storageFence: null, nextEventSeq: 2, terminalReason: null, messageSeq: null,
  };
  const turnEvent = {
    eventId: "completed-event", tenantId: scope.tenantId, turnId: turn.turnId, channelId, seq: 1,
    kind: "turn.completed", messageSeq: 1,
  };
  const dependencies = {
    clock: { now: () => new Date(now * 1000) },
    messages: {
      store: store as never,
      ids: { next: (() => { let value = 0; return () => `message-${++value}`; })() },
      clock: { now: () => new Date(now * 1000) },
      mailbox: { client: dynamo.client as never, tableName: "injected-private-test-store" },
      turns: { async openTurn() { return null; }, async startTurn() { return false; }, async steerTurn() { return false; }, async recordLogicalEnqueue() { return true; } },
      turnRuns: { async enqueue() {} }, turnProbes: { async send() {} },
      listing: {
        client: dynamo.client as never, s3: {} as never,
        messagingTableName: "injected-private-test-store", conversationsTableName: "injected-private-test-store", bucket: "injected-private-test-store",
      },
    },
    turns: {
      store: {
        async getTurn(tenantId: string, turnId: string) { return tenantId === scope.tenantId && turnId === turn.turnId ? turn : null; },
        async listEvents() { return [turnEvent]; },
      } as never,
      clock: { now: () => new Date(now * 1000) }, ids: { next: () => "event" },
    },
  };
  return { channelId, dependencies: dependencies as never, messages };
}

async function main() {
  const auth = prospectusRuntime();
  const core = coreDependencies();
  const options = {
    siteProduct,
    environment: { ...environment, PAPYRUS_PROSPECTUS_SITE_PRODUCT: siteProduct },
    nowInSeconds: () => now,
    resolveRuntime: async () => auth.runtime,
    resolvePrivateDependencies: async () => core.dependencies,
  };
  const send = await handlePapyrusHostedChatRequest(
    requestFor("POST", "editor-a", `channels/${core.channelId}/messages`, {
      author_kind: "bot", author_id: "attacker-chosen", body: "A private newsroom message", addressed_to_bot_id: null,
    }, { origin: "https://papyrus.example", "idempotency-key": "message-key-1" }),
    ["channels", core.channelId, "messages"], options,
  );
  assert.equal(send.status, 200);
  const sendBody = await send.json() as { message: { author_id: string; tenant_id: string; body: string } };
  const expectedScope = derivePapyrusChatScope(siteProduct, accountId, "editor-a");
  assert.equal(sendBody.message.author_id, expectedScope.editorId, "the endpoint replaces client identity with server-derived editor id");
  assert.equal(sendBody.message.tenant_id, expectedScope.tenantId, "tenant scope includes the configured site and selected Account");
  assert.equal(sendBody.message.body, "A private newsroom message");

  const read = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], options);
  assert.equal(read.status, 200);
  const readBody = await read.json() as { messages: Array<{ author_id: string; body: string }> };
  assert.equal(readBody.messages[0]?.author_id, expectedScope.editorId);
  const nonparticipantRead = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-b", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], options);
  assert.equal(nonparticipantRead.status, 403, "same-Account nonparticipants cannot read another private transcript");

  const events = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", "turns/private-turn-a/events"), ["turns", "private-turn-a", "events"], options);
  assert.equal(events.status, 200);
  const eventsBody = await events.json() as { events: Array<{ kind: string }> };
  assert.equal(eventsBody.events[0]?.kind, "turn.completed");
  const stream = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", "turns/private-turn-a/stream"), ["turns", "private-turn-a", "stream"], options);
  assert.equal(stream.status, 200);
  assert.match(await stream.text(), /turn\.completed/);
  const nonparticipantStream = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-b", "turns/private-turn-a/stream"), ["turns", "private-turn-a", "stream"], options);
  assert.equal(nonparticipantStream.status, 403);

  const noSession = await handlePapyrusHostedChatRequest(withNextRequestShape(new Request("https://papyrus.example/api/newsroom/chat/channels/private-channel-a/messages")), ["channels", core.channelId, "messages"], options);
  assert.equal(noSession.status, 401);
  const denied = await handlePapyrusHostedChatRequest(requestFor("GET", "denied-editor", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], options);
  assert.equal(denied.status, 403);
  const noStore = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], { ...options, resolvePrivateDependencies: async () => null });
  assert.equal(noStore.status, 503, "the endpoint fails closed until a private durable store runtime is configured");
  assert.ok(auth.authorizationCalls.some((call) => call.personId === "editor-a" && call.operation === "console:write"));
  assert.ok(auth.authorizationCalls.some((call) => call.personId === "editor-a" && call.operation === "console:read"));
  assert.ok(core.messages.length === 1);
  console.log("PASS: Papyrus gateway uses sealed Prospectus identity and Chatticus private chat core");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
