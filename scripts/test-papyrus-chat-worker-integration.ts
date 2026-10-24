import assert from "node:assert/strict";
import { DeleteItemCommand, PutItemCommand, QueryCommand, TransactWriteItemsCommand, UpdateItemCommand } from "@aws-sdk/client-dynamodb";
import { BACKGROUND_CONTEXT, withoutAbortSignal } from "@earendil-works/chord/context";
import { createProvider } from "@earendil-works/pi-ai/models";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai/utils/event-stream";
import { createModels } from "@earendil-works/pi-ai/models";
import { createRegistry, Harness, MemoryStorage, type Storage } from "@earendil-works/pi-durable";
import { consumeRunJob, Decimal, VendorPriceBook } from "chatticus/chat-worker";
import type { NextRequest } from "next/server";
import { derivePapyrusChatScope, handlePapyrusHostedChatRequest } from "../lib/papyrus-hosted-chat";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";

const siteProduct = "papyrus-demo";
const accountId = "publishing-account-1";
const editorId = "editor-a";
const botId = "papyrus-editorial-assistant";
const now = 1_798_000_000;
const sealingSecret = "papyrus-hosted-chat-test-sealing-secret-32-bytes-minimum";
const environment = { PAPYRUS_SITE_ORIGIN: "https://papyrus.example", NODE_ENV: "test" };
const answer = "The newsroom update is ready.";

function requestFor(method: string, personId: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}) {
	const expiresAt = now + 600;
	const sealed = sealProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, {
		personId,
		accessToken: `access-${personId}`,
		accessTokenExpiresAt: expiresAt,
		selectedAccountId: accountId,
	}, expiresAt);
	const request = new Request(`https://papyrus.example/api/newsroom/chat/${path}`, {
		method,
		headers: {
			cookie: `${PROSPECTUS_SESSION_COOKIE}=${sealed}`,
			...(body === undefined ? {} : { "content-type": "application/json" }),
			...extraHeaders,
		},
		...(body === undefined ? {} : { body: JSON.stringify(body) }),
	});
	Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
	const cookie = request.headers.get("cookie") ?? "";
	const values = new Map(cookie.split(";").map((part) => part.trim().split(/=(.*)/s).slice(0, 2)));
	Object.defineProperty(request, "cookies", { value: { get: (name: string) => values.has(name) ? { value: values.get(name) } : undefined } });
	return request as unknown as NextRequest;
}

function prospectusRuntime() {
	const accounts = {
		async accountDirectory(accessToken: string) {
			const personId = accessToken.slice("access-".length);
			return {
				person: { id: personId },
				accounts: [{ id: accountId, name: "Newsroom", role: "member", products: [{ product: siteProduct, status: "active" }] }],
			};
		},
		async currentPerson(accessToken: string) { return { person: { id: accessToken.slice("access-".length) } }; },
		async authorizeAccountOperation(accessToken: string, requestedAccountId: string, operation: string) {
			return {
				allowed: true,
				personId: accessToken.slice("access-".length),
				accountId: requestedAccountId,
				operation,
				product: siteProduct,
				role: "member",
				revision: 1,
			};
		},
	};
	return { sealingSecret, accounts: accounts as never, cognitoClient: {} as never };
}

function deterministicModel(text: string) {
	const modelId = "papyrus-deterministic-model";
	const model = {
		id: modelId,
		name: modelId,
		api: "scripted",
		provider: "openai",
		baseUrl: "http://localhost:0",
		reasoning: false,
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 128000,
		maxTokens: 1024,
	};
	let callCount = 0;
	const stream = (requestModel: any) => {
		callCount += 1;
		const outer = createAssistantMessageEventStream();
		queueMicrotask(() => {
			const blank = {
				role: "assistant",
				content: [],
				api: requestModel.api,
				provider: requestModel.provider,
				model: requestModel.id,
				usage: { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 15, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
				stopReason: "stop",
				timestamp: Date.now(),
			};
			outer.push({ type: "start", partial: blank } as never);
			const partial = { ...blank, content: [{ type: "text", text }] };
			outer.push({ type: "text_start", contentIndex: 0, partial: { ...blank, content: [{ type: "text", text: "" }] } } as never);
			outer.push({ type: "text_delta", contentIndex: 0, delta: text, partial } as never);
			outer.push({ type: "text_end", contentIndex: 0, content: text, partial } as never);
			const message = { ...partial, usage: blank.usage };
			outer.push({ type: "done", reason: "stop", message } as never);
			outer.end(message as never);
		});
		return outer;
	};
	const provider = createProvider({
		id: "openai",
		auth: { apiKey: { name: "Local deterministic model", resolve: async () => ({ auth: {} }) } },
		models: [model],
		api: {
			stream,
			streamSimple: stream,
		},
	} as never);
	return { modelId, provider, get callCount() { return callCount; } };
}

function makeRuntimeDependencies() {
	const scope = derivePapyrusChatScope(siteProduct, accountId, editorId);
	const bot = { tenantId: scope.tenantId, botId, name: "Editorial assistant", memory: {} };
	let channel: any = null;
	const posts = new Map<string, any>();
	const turnEvents = new Map<string, any[]>();
	const turnRecords = new Map<string, any>();
	const sessions = new Map<string, Storage>();
	const mail = new Map<string, Record<string, any>>();
	const channelSequences = new Map<string, number>();
	const jobs: any[] = [];
	let id = 0;
	const ids = { next: () => `papyrus-id-${++id}` };
	const clock = { now: () => new Date(now * 1000) };
	const mailboxKey = (tenant: string, botKey: string, channelKey: string, seq: number) =>
		`MB#${tenant}#${botKey}#${channelKey}\0${String(seq).padStart(10, "0")}`;
	const putMail = (item: any) => {
		mail.set(mailboxKey(item.tenantId, item.botId, item.channelId, item.seq), {
			pk: { S: `MB#${item.tenantId}#${item.botId}#${item.channelId}` },
			sk: { S: String(item.seq).padStart(10, "0") },
			seq: { N: String(item.seq) },
			message_id: { S: item.messageId },
			author_kind: { S: item.authorKind },
			author_id: { S: item.authorId },
			addressed_to_bot_id: { S: item.addressedToBotId ?? "" },
			body: { S: item.body },
			created_at: { S: item.createdAt },
		});
	};
	const dynamoClient = {
		async send(command: { constructor: { name: string }; input: Record<string, any> }): Promise<any> {
			if (command.constructor.name === UpdateItemCommand.name) {
				const key = command.input.Key as Record<string, { S?: string }>;
				const partition = `${key.pk?.S}\0${key.sk?.S}`;
				const next = (channelSequences.get(partition) ?? 1) + 1;
				channelSequences.set(partition, next);
				return { Attributes: { next_seq: { N: String(next) } } };
			}
			if (command.constructor.name === PutItemCommand.name) {
				const item = command.input.Item as Record<string, any>;
				mail.set(`${item.pk?.S}\0${item.sk?.S}`, item);
				return {};
			}
			if (command.constructor.name === QueryCommand.name) {
				const values = command.input.ExpressionAttributeValues as Record<string, { S?: string }>;
				const partition = values[":pk"]?.S;
				const after = values[":after"]?.S ?? "";
				return { Items: [...mail.values()].filter((item) => item.pk?.S === partition && item.sk?.S > after) };
			}
			if (command.constructor.name === DeleteItemCommand.name) {
				const key = command.input.Key as Record<string, { S?: string }>;
				mail.delete(`${key.pk?.S}\0${key.sk?.S}`);
				return {};
			}
			if (command.constructor.name === TransactWriteItemsCommand.name) return {};
			if (command.constructor.name === GetItemCommand.name) return {};
			throw new Error(`Unexpected local DynamoDB command ${command.constructor.name}`);
		},
	};
	const store = {
		async getBot(tenantId: string, requestedBotId: string) { return tenantId === bot.tenantId && requestedBotId === botId ? bot : null; },
		async getChannel(tenantId: string, requestedChannelId: string) { return tenantId === scope.tenantId && requestedChannelId === channel?.channelId ? channel : null; },
		async listChannels(tenantId: string, userId: string) {
			return channel && channel.tenantId === tenantId && channel.participants.some((participant: any) => participant.kind === "human" && participant.actorId === userId) ? [channel] : [];
		},
		async putChannelIfAbsent(value: any) { channel ??= value; return channel; },
		async resolveChannelTenant(requestedChannelId: string) { return requestedChannelId === channel?.channelId ? channel.tenantId : null; },
		async getPostIdempotency(tenantId: string, key: string) { return posts.get(`${tenantId}\0${key}`)?.result ?? null; },
		async reservePostIdempotency(tenantId: string, key: string, fingerprint: string, candidate: any) {
			const storageKey = `${tenantId}\0${key}`;
			const prior = posts.get(storageKey);
			if (prior?.fingerprint !== undefined && prior.fingerprint !== fingerprint) return { state: "conflict" };
			if (prior?.result) return { state: "completed", result: prior.result };
			if (prior) return { state: "busy" };
			const reservation = { ...candidate, seq: null, admission: null };
			posts.set(storageKey, { fingerprint, reservation, result: null });
			return { state: "owner", reservation };
		},
		async setPostIdempotencySequence(tenantId: string, key: string, ownerId: string, seq: number) {
			const record = posts.get(`${tenantId}\0${key}`);
			if (!record || record.reservation.ownerId !== ownerId) return null;
			record.reservation.seq ??= seq;
			return record.reservation.seq;
		},
		async completePostIdempotency(tenantId: string, key: string, ownerId: string, message: any, turnId: string | null) {
			const record = posts.get(`${tenantId}\0${key}`);
			if (!record || record.reservation.ownerId !== ownerId) return false;
			record.result = { message, turnId };
			return true;
		},
	};
	const turnStore = {
		async getTurn(tenantId: string, turnId: string) { return tenantId === scope.tenantId ? turnRecords.get(turnId) ?? null : null; },
		async claimTurn(request: any) {
			const turn = turnRecords.get(request.turnId);
			if (!turn || turn.status !== "active" || turn.attemptId !== null) return null;
			Object.assign(turn, { attemptId: request.attemptId, attempt: turn.attempt + 1, claimedBy: request.claimedBy, leaseExpiresAt: request.leaseExpiresAt, deadlineAt: request.deadlineAt });
			return turn;
		},
		async renewTurn(request: any) {
			const turn = turnRecords.get(request.turnId);
			if (!turn || turn.status !== "active" || turn.attemptId !== request.attemptId) return null;
			turn.leaseExpiresAt = request.leaseExpiresAt;
			turn.deadlineAt = request.deadlineAt;
			return turn;
		},
		async recordStorageFence(tenantId: string, turnId: string, attemptId: string, fence: number) {
			const turn = turnRecords.get(turnId);
			if (!turn || turn.attemptId !== attemptId) throw new Error("stale worker attempt");
			turn.storageFence = fence;
		},
		async appendEvent(request: any) {
			const turn = turnRecords.get(request.turnId);
			if (!turn || turn.status !== "active" || turn.attemptId !== request.attemptId) throw new Error("stale worker event");
			const events = turnEvents.get(request.turnId)!;
			const event = { ...request.draft, eventId: request.eventId, tenantId: scope.tenantId, turnId: request.turnId, channelId: turn.channelId, seq: turn.nextEventSeq++ };
			events.push(event);
			return event;
		},
		async beginClosing() {},
		async completeTurn(request: any) {
			const turn = turnRecords.get(request.turnId);
			if (!turn || turn.attemptId !== request.attemptId) throw new Error("stale worker completion");
			turn.status = "completed";
			turn.messageSeq = request.messageSeq;
			const event = { kind: "turn.completed", body: request.body, messageSeq: request.messageSeq, eventId: request.eventId, tenantId: scope.tenantId, turnId: request.turnId, channelId: turn.channelId, seq: turn.nextEventSeq++ };
			turnEvents.get(request.turnId)!.push(event);
			return event;
		},
		async failTurn(request: any) {
			const turn = turnRecords.get(request.turnId);
			if (!turn) throw new Error("turn not found");
			turn.status = "failed";
			const event = { kind: "turn.failed", body: request.reason, eventId: request.eventId, tenantId: scope.tenantId, turnId: request.turnId, channelId: turn.channelId, seq: turn.nextEventSeq++ };
			turnEvents.get(request.turnId)!.push(event);
			return event;
		},
		async listEvents(tenantId: string, turnId: string, after: number) { return tenantId === scope.tenantId ? (turnEvents.get(turnId) ?? []).filter((event: any) => event.seq > after) : []; },
		async getGrant() { return null; },
	};
	const queue = {
		async enqueue(job: any) { jobs.push(job); },
	};
	const probes = { async send() {} };
	const turns = {
		store: turnStore,
		clock,
		ids,
		async openTurn() { return null; },
		async startTurn(request: any) {
			const turn = {
				turnId: request.turnId,
				tenantId: request.tenantId,
				channelId: request.channelId,
				botId: request.botId,
				status: "active",
				promptMessageSeq: request.promptMessageSeq,
				promptAuthorId: request.promptAuthorId,
				attemptId: null,
				attempt: 0,
				claimedBy: null,
				leaseExpiresAt: null,
				deadlineAt: null,
				recoveryAttempts: 0,
				waitingFor: null,
				waitingSince: null,
				logicalEnqueueIds: [],
				pendingComputerTool: null,
				storageFence: null,
				nextEventSeq: 2,
				terminalReason: null,
				messageSeq: null,
			};
			turnRecords.set(request.turnId, turn);
			turnEvents.set(request.turnId, [{ eventId: request.startedEventId, tenantId: request.tenantId, turnId: request.turnId, channelId: request.channelId, seq: 1, kind: "turn.started" }]);
			if (request.initialItem) putMail(request.initialItem);
			return true;
		},
		async steerTurn() { return false; },
		async recordLogicalEnqueue() { return true; },
	};
	const mailbox = { client: dynamoClient, tableName: "local-test" };
	const messaging = {
		store,
		ids,
		clock,
		mailbox,
		turns,
		turnRuns: queue,
		turnProbes: probes,
		listing: {
			client: dynamoClient,
			s3: {} as never,
			messagingTableName: "local-test",
			conversationsTableName: "local-test",
			bucket: "local-test",
			openExistingStorage: async (storageId: string) => sessions.get(storageId),
		},
	};
	const dependencies = {
		clock,
		messages: messaging,
		turns: { store: turnStore, clock, ids },
		resolvePrincipal: async () => null,
		privateConversation: { assistantBotId: botId },
	};
	const sessionFactory = async (storageId: string, sessionDeps: any) => {
		const storage = new MemoryStorage();
		const wrapped = new Proxy(storage, {
			get(target, property) {
				if (property === "close") return async () => undefined;
				const value = Reflect.get(target, property, target);
				return typeof value === "function" ? value.bind(target) : value;
			},
		}) as Storage;
		const registry = createRegistry();
		for (const extension of sessionDeps.extensions) registry.install(extension);
		const harness = await Harness.open(wrapped, { models: sessionDeps.models, registry, settings: sessionDeps.settings }, sessionDeps.context);
		sessions.set(storageId, storage);
		return { harness, storage, fence: 1, close: () => harness.close(withoutAbortSignal(sessionDeps.context)) };
	};
	return { scope, bot, messaging, dependencies, turns: turnRecords, turnStore, turnEvents, queue, probes, mailbox, dynamoClient, sessions, sessionFactory, jobs };
}

async function main() {
	const scope = derivePapyrusChatScope(siteProduct, accountId, editorId);
	const core = makeRuntimeDependencies();
	const fakeStore = core.messaging.store as any;
	const privateDependencies = {
		...core.dependencies,
		messages: {
			...core.messaging,
			store: fakeStore,
		},
		resolvePrincipal: async (request: Request) => {
			void request;
			return null;
		},
	};
	const options = {
		siteProduct,
		environment: { ...environment, PAPYRUS_PROSPECTUS_SITE_PRODUCT: siteProduct },
		nowInSeconds: () => now,
		resolveRuntime: async () => prospectusRuntime(),
		resolvePrivateDependencies: async () => privateDependencies as never,
	};
	const createResponse = await handlePapyrusHostedChatRequest(
		requestFor("POST", editorId, "private-channel", undefined, { origin: "https://papyrus.example" }),
		["private-channel"],
		options,
	);
	if (createResponse.status !== 200) throw new Error(`Private conversation creation returned ${createResponse.status}: ${await createResponse.text()}`);
	const created = await createResponse.json() as { channel_id: string; tenant_id: string };
	assert.equal(created.tenant_id, scope.tenantId);
	const openAgain = await handlePapyrusHostedChatRequest(
		requestFor("POST", editorId, "private-channel", undefined, { origin: "https://papyrus.example" }),
		["private-channel"],
		options,
	);
	assert.equal((await openAgain.json() as { channel_id: string }).channel_id, created.channel_id);

	const scripted = deterministicModel(answer);
	const models = createModels();
	models.setProvider(scripted.provider as never);
	const prices = new VendorPriceBook("local-integration-test");
	prices.register("openai", scripted.modelId, { inputPerMillionUsd: Decimal.parse("1"), outputPerMillionUsd: Decimal.parse("2") });
	const sendHeaders = { origin: "https://papyrus.example", "idempotency-key": "newsroom-message-1" };
	const sent = await handlePapyrusHostedChatRequest(
		requestFor("POST", editorId, `channels/${created.channel_id}/messages`, { body: "Draft an update", addressed_to_bot_id: botId }, sendHeaders),
		["channels", created.channel_id, "messages"],
		options,
	);
	if (sent.status !== 200) throw new Error(`Hosted message send returned ${sent.status}: ${await sent.text()}`);
	const sentBody = await sent.json() as { message: { author_id: string; seq: number }; turn_id: string };
	assert.equal(sentBody.message.author_id, scope.editorId);
	assert.equal(sentBody.message.seq, 1);
	const sentMessageId = (sentBody as any).message.message_id as string;
	assert.equal(core.jobs.length, 1);

	const job = core.jobs.shift()!;
	const turnDependencies = {
		turns: { store: core.turnStore, clock: { now: () => new Date(now * 1000) }, ids: { next: (() => { let id = 0; return () => `worker-event-${++id}`; })() } },
		messaging: fakeStore,
		client: core.dynamoClient,
		s3: {} as never,
		messagingTableName: "local-test",
		conversationsTableName: "local-test",
		piSessionsBucket: "local-test",
		models,
		model: { provider: "openai", modelId: scripted.modelId, thinkingLevel: "off" },
		ledger: { client: core.dynamoClient, tableName: "local-test", prices, now: () => new Date(now * 1000) },
		ownerKind: "lambda",
		executionProfile: "computerless",
		sessionFactory: core.sessionFactory,
		turnRuns: { async enqueue() {} },
		turnProbes: { async send() {} },
		runVisibility: { async extend() {} },
		computer: {} as never,
		tuning: { renewIntervalMilliseconds: 60_000, mailboxPollMilliseconds: 2 },
	} as never;
	let acknowledgements = 0;
	assert.equal(await consumeRunJob(job, turnDependencies, async () => { acknowledgements += 1; }), "done");
	assert.equal(acknowledgements, 1);
	assert.equal(scripted.callCount, 1);
	const completion = (core.turnEvents.get(sentBody.turn_id) ?? []).find((event: any) => event.kind === "turn.completed");
	assert.equal(completion?.body, answer);

	const refreshed = await handlePapyrusHostedChatRequest(
		requestFor("GET", editorId, `channels/${created.channel_id}/messages`),
		["channels", created.channel_id, "messages"],
		options,
	);
	if (refreshed.status !== 200) throw new Error(`Hosted message refresh returned ${refreshed.status}: ${await refreshed.text()}`);
	const messages = (await refreshed.json() as { messages: Array<{ author_kind: string; body: string; seq: number }> }).messages;
	assert.deepEqual(messages.map((message) => [message.author_kind, message.body, message.seq]), [
		["human", "Draft an update", 1],
		["bot", answer, 2],
	]);
	const replay = await handlePapyrusHostedChatRequest(
		requestFor("POST", editorId, `channels/${created.channel_id}/messages`, { body: "Draft an update", addressed_to_bot_id: botId }, sendHeaders),
		["channels", created.channel_id, "messages"],
		options,
	);
	assert.equal(replay.status, 200);
	assert.equal((await replay.json() as { message: { message_id: string } }).message.message_id, sentMessageId);
	assert.equal(core.jobs.length, 0);
	assert.equal(scripted.callCount, 1);

	const afterPrompt = await handlePapyrusHostedChatRequest(
		requestFor("GET", editorId, `channels/${created.channel_id}/messages?after=1`),
		["channels", created.channel_id, "messages"],
		options,
	);
	assert.deepEqual((await afterPrompt.json() as { messages: Array<{ body: string }> }).messages.map((message) => message.body), [answer]);
	const foreignRead = await handlePapyrusHostedChatRequest(
		requestFor("GET", "editor-b", `channels/${created.channel_id}/messages`),
		["channels", created.channel_id, "messages"],
		options,
	);
	assert.equal(foreignRead.status, 403);
	for (const storage of core.sessions.values()) await storage.close();
	console.log("PASS: Papyrus private channel, hosted send, shared worker reply, refresh/replay, and foreign-editor denial");
}

main().catch((error) => {
	console.error(error);
	process.exit(1);
});
