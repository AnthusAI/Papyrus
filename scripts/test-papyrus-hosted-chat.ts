import assert from "node:assert/strict";
import { GetItemCommand, PutItemCommand, QueryCommand, UpdateItemCommand } from "@aws-sdk/client-dynamodb";
import type { NextRequest } from "next/server";
import { expireChatStream, derivePapyrusChatScope, handlePapyrusHostedChatRequest } from "../lib/papyrus-hosted-chat";

const publicationNamespace = JSON.stringify(["private-bucket", "private-table", "newsroom-client"]);
const issuer = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Test";
const now = 1_798_000_000;
const environment = { PAPYRUS_SITE_ORIGIN: "https://papyrus.example", NODE_ENV: "test", PAPYRUS_CHAT_SESSION_BUCKET: "private-bucket", PAPYRUS_CHAT_MESSAGING_TABLE: "private-table" };

function requestFor(method: string, personId: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  return withNextRequestShape(new Request(`https://papyrus.example/api/newsroom/chat/${path}`, {
    method,
    headers: {
      authorization: `Bearer ${personId}`,
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

function coreDependencies(scope = derivePapyrusChatScope(publicationNamespace, issuer, "editor-a"), running = false) {
  const channelId = "private-channel-a";
  const messages: any[] = [];
  const completed = new Map<string, { message: any; turnId: string | null }>();
  const store = {
    async resolveChannelTenant() { return scope.tenantId; },
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
    turnId: "private-turn-a", tenantId: scope.tenantId, channelId, botId: "editorial-assistant", status: running ? "running" : "completed",
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
      turns: {
        async openTurn() { return null; },
        async startTurn(request: any) {
          const item = request.initialItem;
          if (item) {
            const pk = `MB#${item.tenantId}#${item.botId}#${item.channelId}`;
            const sk = String(item.seq).padStart(10, "0");
            dynamo.items.set(`${pk}\0${sk}`, {
              pk: { S: pk }, sk: { S: sk }, seq: { N: String(item.seq) }, message_id: { S: item.messageId },
              author_kind: { S: item.authorKind }, author_id: { S: item.authorId }, body: { S: item.body },
              addressed_to_bot_id: { S: item.addressedToBotId ?? "" }, created_at: { S: item.createdAt },
            });
          }
          return true;
        },
        async steerTurn() { return true; }, async recordLogicalEnqueue() { return true; },
      },
      turnRuns: { async enqueue() {} }, turnProbes: { async send() {} },
      listing: {
        client: dynamo.client as never, s3: {} as never,
        messagingTableName: "injected-private-test-store", conversationsTableName: "injected-private-test-store", bucket: "injected-private-test-store",
      },
    },
    turns: {
      store: {
        async getTurn(tenantId: string, turnId: string) { return tenantId === scope.tenantId && turnId === turn.turnId ? turn : null; },
        async listEvents() { return running ? [] : [turnEvent]; },
      } as never,
      clock: { now: () => new Date(now * 1000) }, ids: { next: () => "event" },
    },
  };
  return { channelId, dependencies: dependencies as never, messages };
}

async function main() {
  let cancelled = false;
  const streamAtExpiry = expireChatStream(new Response(new ReadableStream({ cancel() { cancelled = true; } })), 5);
  assert.equal(await streamAtExpiry.text(), "");
  assert.equal(cancelled, true, "JWT expiry closes and cancels the underlying event stream");

  const sharedRuntime = await import("chatticus/chat-runtime");
  const runtimeEnvironment = {
    PAPYRUS_CHAT_MESSAGING_TABLE: "PapyrusPrivateMessages",
    PAPYRUS_CHAT_CONVERSATIONS_TABLE: "PapyrusPrivateIndex",
    PAPYRUS_CHAT_SESSION_BUCKET: "papyrus-private-sessions",
    PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL: "https://sqs.us-east-1.amazonaws.com/111111111111/private-runs",
    PAPYRUS_CHAT_TURN_PROBES_QUEUE_URL: "https://sqs.us-east-1.amazonaws.com/111111111111/private-probes",
    PAPYRUS_CHAT_PRIVATE_BOT_ID: "papyrus-newsroom",
    PAPYRUS_CHAT_PRIVATE_BOT_NAME: "Papyrus newsroom assistant",
    OPENAI_API_KEY: "test-only-no-request",
  };
  let awsRequests = 0;
  const clients = {
    dynamo: { send: async () => { awsRequests += 1; return {}; } },
    s3: { send: async () => { awsRequests += 1; return {}; } },
    sqs: { send: async () => { awsRequests += 1; return {}; } },
    parameters: { send: async () => { awsRequests += 1; return {}; } },
  } as never;
  const resources = sharedRuntime.siteHostedChatResourcesFromEnvironment(runtimeEnvironment);
  const composed = sharedRuntime.createSiteHostedChatDependencies(resources, clients) as any;
  assert.equal(composed.messages.store.constructor.name, "DynamoMessagingStore");
  assert.equal(composed.messages.turns.constructor.name, "DynamoTurnAdmission");
  assert.equal(composed.messages.turnRuns.constructor.name, "SqsTurnRunQueue");
  assert.equal(composed.turns.store.constructor.name, "DynamoTurnControlStore");
  await sharedRuntime.createSiteHostedRunHandler(runtimeEnvironment, clients)({ Records: [] }, { getRemainingTimeInMillis: () => 30_000 });
  await sharedRuntime.createSiteHostedProbeHandler(runtimeEnvironment, clients)({ Records: [] });
  assert.equal(awsRequests, 0, "adapter construction and empty Lambda batches make no AWS requests");

  const core = coreDependencies();
  const options = {
    privateChatEnabled: true,
    environment: { ...environment, PAPYRUS_CHAT_PRIVATE_BOT_ID: "editorial-assistant" },
    nowInSeconds: () => now,

    resolveNewsroomIdentity: async (request: NextRequest) => { const subject = request.headers.get("authorization")?.replace("Bearer ", ""); return subject && subject !== "denied-editor" ? { subject, issuer, clientId: "newsroom-client", expiresAt: now + 600 } : null; },
    resolvePrivateDependencies: async () => core.dependencies,
  };
  const send = await handlePapyrusHostedChatRequest(
    requestFor("POST", "editor-a", `channels/${core.channelId}/messages`, {
      author_kind: "bot", author_id: "attacker-chosen", body: "A private newsroom message", addressed_to_bot_id: null,
    }, { origin: "https://papyrus.example", "idempotency-key": "message-key-1" }),
    ["channels", core.channelId, "messages"], options,
  );
  assert.equal(send.status, 200);
  const sendBody = await send.json() as { message: { author_kind: string; author_id: string; tenant_id: string; body: string; addressed_to_bot_id: string | null } };
  const expectedScope = derivePapyrusChatScope(publicationNamespace, issuer, "editor-a");
  assert.equal(sendBody.message.author_id, expectedScope.editorId, "the endpoint replaces client identity with server-derived editor id");
  assert.equal(sendBody.message.author_kind, "human", "the endpoint replaces client actor kind with the authenticated editor");
  assert.equal(sendBody.message.tenant_id, expectedScope.tenantId, "tenant scope includes the configured publication and issuer");
  assert.equal(sendBody.message.body, "A private newsroom message");
  assert.equal(sendBody.message.addressed_to_bot_id, "editorial-assistant", "the endpoint chooses the private assistant from server configuration");

  const read = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], options);
  assert.equal(read.status, 200);
  const readBody = await read.json() as { messages: Array<{ author_id: string; body: string }> };
  assert.equal(readBody.messages[0]?.author_id, expectedScope.editorId, JSON.stringify(readBody.messages));
  const nonparticipantRead = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-b", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], options);
  assert.equal(nonparticipantRead.status, 403, "nonparticipants cannot read another private transcript");

  const events = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", "turns/private-turn-a/events"), ["turns", "private-turn-a", "events"], options);
  assert.equal(events.status, 200);
  const eventsBody = await events.json() as { events: Array<{ kind: string }> };
  assert.equal(eventsBody.events[0]?.kind, "turn.completed");
  const stream = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", "turns/private-turn-a/stream"), ["turns", "private-turn-a", "stream"], options);
  assert.equal(stream.status, 200);
  assert.match(await stream.text(), /turn\.completed/);
  const nonparticipantStream = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-b", "turns/private-turn-a/stream"), ["turns", "private-turn-a", "stream"], options);
  assert.equal(nonparticipantStream.status, 403);

  const newsroomOnly = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`, undefined, { cookie: "" }), ["channels", core.channelId, "messages"], options);
  assert.equal(newsroomOnly.status, 200, "existing newsroom session suffices without a Prospectus cookie");
  const foreignSite = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], { ...options, environment: { ...options.environment, PAPYRUS_CHAT_SESSION_BUCKET: "another-publication" } });
  assert.ok([403, 404].includes(foreignSite.status), "a different configured publication cannot read this channel");
  const oldCore = coreDependencies({ tenantId: "papyrus-old-account-tenant", editorId: "papyrus-editor-old-person" });
  const oldHistory = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], { ...options, resolvePrivateDependencies: async () => oldCore.dependencies });
  assert.equal(oldHistory.status, 403, "new newsroom scope cannot adopt old Account history");
  for (const endpoint of ["events", "stream"]) {
    const path = ["turns", "private-turn-a", endpoint];
    for (const boundary of [
      { ...options, environment: { ...options.environment, PAPYRUS_CHAT_SESSION_BUCKET: "another-publication" } },
      { ...options, resolvePrivateDependencies: async () => oldCore.dependencies },
      { ...options, resolveNewsroomIdentity: async () => ({ subject: "editor-a", issuer, clientId: "another-publication-client", expiresAt: now + 600 }) },
    ]) {
      const refused = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", path.join("/")), path, boundary);
      assert.ok([403, 404].includes(refused.status), `${endpoint} refuses foreign publication/client and old history`);
    }
  }
  const activeCore = coreDependencies(undefined, true);
  const gatewayStream = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", "turns/private-turn-a/stream"), ["turns", "private-turn-a", "stream"], {
    ...options,
    resolvePrivateDependencies: async () => activeCore.dependencies,
    resolveNewsroomIdentity: async () => ({ subject: "editor-a", issuer, clientId: "newsroom-client", expiresAt: now + 0.02 }),
  });
  assert.equal(gatewayStream.status, 200);
  assert.equal(await gatewayStream.text(), "", "gateway closes a live nonterminal stream at its verified token expiry");
  const unconfigured = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], { ...options, environment: { ...options.environment, PAPYRUS_CHAT_SESSION_BUCKET: "" } });
  assert.equal(unconfigured.status, 503);
  assert.ok(expectedScope.tenantId.startsWith("papyrus-newsroom-v1-"));
  assert.notEqual(derivePapyrusChatScope(publicationNamespace, "another-issuer", "editor-a").editorId, expectedScope.editorId);
  const noSession = await handlePapyrusHostedChatRequest(withNextRequestShape(new Request("https://papyrus.example/api/newsroom/chat/channels/private-channel-a/messages")), ["channels", core.channelId, "messages"], options);
  assert.equal(noSession.status, 401);
  const denied = await handlePapyrusHostedChatRequest(requestFor("GET", "denied-editor", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], options);
  assert.equal(denied.status, 401);
  const expiredOptions = { ...options, resolveNewsroomIdentity: async () => ({ subject: "editor-a", issuer, clientId: "newsroom-client", expiresAt: now - 1 }) };
  const expiredRead = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], expiredOptions);
  assert.equal(expiredRead.status, 401);
  const expiredSend = await handlePapyrusHostedChatRequest(requestFor("POST", "editor-a", `channels/${core.channelId}/messages`, { body: "must not be stored" }, { origin: "https://papyrus.example", "idempotency-key": "expired" }), ["channels", core.channelId, "messages"], expiredOptions);
  assert.equal(expiredSend.status, 401);
  assert.equal(core.messages.length, 1);
  const noStore = await handlePapyrusHostedChatRequest(requestFor("GET", "editor-a", `channels/${core.channelId}/messages`), ["channels", core.channelId, "messages"], { ...options, resolvePrivateDependencies: async () => null });
  assert.equal(noStore.status, 503, "the endpoint fails closed until a private durable store runtime is configured");
  let disabledDependencyLoads = 0;
  const disabled = await handlePapyrusHostedChatRequest(
    requestFor("GET", "editor-a", `channels/${core.channelId}/messages`),
    ["channels", core.channelId, "messages"],
    { ...options, privateChatEnabled: false, resolvePrivateDependencies: async () => { disabledDependencyLoads += 1; return core.dependencies; } },
  );
  assert.equal(disabled.status, 404);
  assert.equal(disabledDependencyLoads, 0);
  assert.ok(core.messages.length === 1);
  console.log("PASS: Papyrus gateway uses verified newsroom identity and Chatticus private chat core; private route remains default-off");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
