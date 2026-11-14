import { randomUUID } from "node:crypto";
import { GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { ChangeMessageVisibilityCommand, ReceiveMessageCommand, SQSClient } from "@aws-sdk/client-sqs";
import { createSiteHostedChatApp, siteHostedChatResourcesFromEnvironment } from "chatticus/chat-runtime";

function assert(condition: unknown, message: string): asserts condition {
	if (!condition) throw new Error(`Synthetic adapter test failed: ${message}`);
}

async function json(response: Response): Promise<Record<string, any>> {
	assert(response.ok, `HTTP ${response.status}: ${await response.text()}`);
	return response.json() as Promise<Record<string, any>>;
}

export async function handler(): Promise<Record<string, unknown>> {
	const resources = siteHostedChatResourcesFromEnvironment(process.env);
	const invocationId = randomUUID();
	const tenantId = `synthetic-adapter-test-${invocationId}`;
	const userId = `synthetic-editor-${invocationId}`;
	const principal = {
		kind: "user" as const,
		tenantId,
		userId,
		workerId: null,
		organizationStatus: "enabled" as const,
		role: "member" as const,
	};
	const app = createSiteHostedChatApp(process.env, async () => principal);
	const privateChannel = await json(await app.fetch(new Request("https://synthetic-adapter.invalid/private-channel", { method: "POST" })));
	const channel = privateChannel as { channel_id?: string };
	assert(typeof channel.channel_id === "string", "private channel creation returns a channel id");

	const requestKey = `synthetic-${invocationId}`;
	const postBody = {
		author_kind: "human",
		author_id: userId,
		body: `Synthetic adapter assertion ${invocationId}`,
		addressed_to_bot_id: resources.assistantBotId,
	};
	const post = async () => json(await app.fetch(new Request(
		`https://synthetic-adapter.invalid/channels/${channel.channel_id}/messages`,
		{ method: "POST", headers: { "content-type": "application/json", "idempotency-key": requestKey }, body: JSON.stringify(postBody) },
	)));
	const first = await post();
	const firstMessage = first.message as { message_id?: string; body?: string };
	assert(typeof firstMessage?.message_id === "string", "send returns a persisted message id");
	assert(firstMessage.body === postBody.body, "send preserves the synthetic message");
	const replay = await post();
	assert((replay.message as { message_id?: string })?.message_id === firstMessage.message_id, "idempotent replay returns the stored message");

	const listed = await json(await app.fetch(new Request(
		`https://synthetic-adapter.invalid/channels/${channel.channel_id}/messages`, { method: "GET" },
	)));
	const messages = listed.messages as Array<{ message_id?: string; body?: string }>;
	assert(messages.some((message) => message.message_id === firstMessage.message_id && message.body === postBody.body), "read returns the persisted synthetic message");

	const s3 = new S3Client({});
	const objectKey = `conversations/synthetic-adapter-tests/${invocationId}.txt`;
	await s3.send(new PutObjectCommand({ Bucket: resources.sessionBucket, Key: objectKey, Body: `synthetic object ${invocationId}` }));
	const storedObject = await s3.send(new GetObjectCommand({ Bucket: resources.sessionBucket, Key: objectKey }));
	assert(await storedObject.Body?.transformToString() === `synthetic object ${invocationId}`, "S3 adapter round-trip returns the synthetic object");

	const sqs = new SQSClient({});
	const queueMessage = await sqs.send(new ReceiveMessageCommand({ QueueUrl: resources.turnRunsQueueUrl, MaxNumberOfMessages: 10, WaitTimeSeconds: 2 }));
	const run = queueMessage.Messages?.find((message) => message.Body?.includes(first.turn_id as string));
	assert(run?.ReceiptHandle, "send publishes a run job for the synthetic turn");
	await sqs.send(new ChangeMessageVisibilityCommand({ QueueUrl: resources.turnRunsQueueUrl, ReceiptHandle: run.ReceiptHandle, VisibilityTimeout: 0 }));

	return {
		ok: true,
		mode: "synthetic-adapter-only",
		invocationId,
		channelId: channel.channel_id,
		messageId: firstMessage.message_id,
		turnId: first.turn_id,
		objectKey,
		queueMessageRetained: true,
		modelCalled: false,
	};
}
