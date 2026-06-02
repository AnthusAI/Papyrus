import {
  buildSlackPrompt,
  chatMessageIdForSlackEvent,
  shouldIgnoreSlackEvent,
  slackSigningSecret,
  slackThreadId,
  verifySlackRequestSignature,
} from "../shared/slack-events";
import { enqueueConsoleChatTurn } from "../shared/console-chat-enqueue";
import { getLambdaDataClient, LAMBDA_DATA_AUTH_MODE } from "../shared/lambda-data-client";

type FunctionUrlEvent = {
  headers?: Record<string, string | undefined>;
  body?: string | null;
  isBase64Encoded?: boolean;
};

export const handler = async (event: FunctionUrlEvent) => {
  const rawBody = decodeBody(event);
  const headers = normalizeHeaders(event.headers ?? {});
  const timestamp = headers["x-slack-request-timestamp"] ?? "";
  const signature = headers["x-slack-signature"] ?? "";

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(rawBody.toString("utf8")) as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid-json" });
  }

  const payloadType = String(payload.type ?? "").trim();
  if (payloadType === "url_verification") {
    // Slack only checks that the endpoint echoes `challenge` (no signature on this step).
    // Match slack_agent.py; real events below still require a valid signing secret.
    const challenge = String(payload.challenge ?? "").trim();
    if (!challenge) {
      return jsonResponse(400, { ok: false, error: "missing-challenge" });
    }
    return jsonResponse(200, { challenge });
  }

  let secret: string;
  try {
    secret = await slackSigningSecret();
  } catch (error) {
    return jsonResponse(500, {
      ok: false,
      error: error instanceof Error ? error.message : "PAPYRUS_SLACK_SIGNING_SECRET is not configured.",
    });
  }
  if (!verifySlackRequestSignature({ signingSecret: secret, timestamp, rawBody, signature })) {
    return jsonResponse(401, { ok: false, error: "invalid-slack-signature" });
  }

  if (payloadType !== "event_callback") {
    return jsonResponse(200, { ok: true, ignored: true, reason: `unsupported-type:${payloadType || "missing"}` });
  }

  const eventId = String(payload.event_id ?? "").trim();
  const teamId = String(payload.team_id ?? "").trim() || null;
  const slackEvent = payload.event;
  if (!slackEvent || typeof slackEvent !== "object") {
    return jsonResponse(400, { ok: false, error: "missing-event" });
  }

  const eventRecord = slackEvent as Record<string, unknown>;
  const eventType = String(eventRecord.type ?? "").trim();
  if (eventType !== "message" && eventType !== "app_mention") {
    return jsonResponse(200, { ok: true, ignored: true, reason: `unsupported-event:${eventType}` });
  }

  const ignoreReason = shouldIgnoreSlackEvent(eventRecord);
  if (ignoreReason) {
    return jsonResponse(200, { ok: true, ignored: true, reason: ignoreReason });
  }

  const channelId = String(eventRecord.channel ?? "").trim();
  const threadTs = String(eventRecord.thread_ts ?? eventRecord.ts ?? "").trim();
  if (!channelId || !threadTs) {
    return jsonResponse(400, { ok: false, error: "missing-channel-or-ts" });
  }

  const resolvedEventId = eventId || `${eventType}-${threadTs}`;
  const chatMessageId = chatMessageIdForSlackEvent(resolvedEventId);
  const dataClient = await getLambdaDataClient();
  const existing = await dataClient.models.Message.get(
    { id: chatMessageId },
    { authMode: LAMBDA_DATA_AUTH_MODE },
  );
  if (existing.data?.id) {
    return jsonResponse(200, { ok: true, idempotent: true, chatMessageId });
  }

  const user = String(eventRecord.user ?? "slack-user").trim();
  const threadId = slackThreadId(teamId ?? "", channelId, threadTs);
  const prompt = buildSlackPrompt({
    event: eventRecord,
    teamId,
    channelId,
    threadTs,
  });

  const chat = await enqueueConsoleChatTurn(dataClient, {
    threadId,
    threadTitle: `Slack ${channelId}`,
    threadSummary: "Slack agent conversation",
    primaryAnchorKind: "slack_thread",
    primaryAnchorId: threadId,
    createdByLabel: `slack:${user}`,
    prompt,
    messageSummary: String(eventRecord.text ?? "Slack message").slice(0, 180),
    source: "slack",
    channel: "slack",
    channelMetadata: {
      slackTeamId: teamId,
      slackChannelId: channelId,
      slackThreadTs: threadTs,
      slackUserId: user,
      slackEventId: resolvedEventId,
    },
    threadMetadata: {
      slackTeamId: teamId,
      slackChannelId: channelId,
      slackThreadTs: threadTs,
    },
    captureModelContext: true,
    chatMessageId,
  });

  return jsonResponse(200, { ok: true, chat, eventId: resolvedEventId });
};

function decodeBody(event: FunctionUrlEvent): Buffer {
  const body = event.body ?? "";
  if (event.isBase64Encoded) {
    return Buffer.from(body, "base64");
  }
  return Buffer.from(body, "utf8");
}

function normalizeHeaders(headers: Record<string, string | undefined>): Record<string, string> {
  const normalized: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    if (typeof value === "string") normalized[key.toLowerCase()] = value;
  }
  return normalized;
}

function jsonResponse(statusCode: number, body: unknown) {
  return {
    statusCode,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}
