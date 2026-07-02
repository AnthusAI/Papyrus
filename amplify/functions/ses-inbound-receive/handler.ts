import { InvokeCommand, LambdaClient } from "@aws-sdk/client-lambda";
import { GetObjectCommand, ListObjectsV2Command, S3Client } from "@aws-sdk/client-s3";
import {
  buildEmailSubmissionMessageInput,
  classifyInboundEmailIntake,
  countInboundAttachments,
  extractDirectCitations,
  extractRecipientsFromRawMime,
  extractRecipientsFromSesMail,
  extractSenderFromRawMime,
  extractSenderFromSesMail,
  extractUserComposedReplyText,
  looksLikeResearchAssignmentRequest,
  lookupRegisteredUserProfileId,
  normalizeEmailAddress,
  parseInboundEmailBody,
  parseInboundMimeThreading,
  resolveParentSubmissionMessageId,
  UNREGISTERED_SENDER_RESPONSE_ERROR,
} from "../shared/email-submission";
import { parseInboundMimeForIntake } from "../shared/email-mime-intake";
import {
  inboundMessageIdFromS3,
  parseMessageMetadata,
  shouldProcessInboundS3Key,
} from "../shared/inbound-email-intake";
import { getLambdaDataClient, LAMBDA_DATA_AUTH_MODE } from "../shared/lambda-data-client";
import { putTextModelPayload } from "../shared/model-payloads";

const PROCESSOR_FUNCTION_NAME = process.env.PAPYRUS_EMAIL_SUBMISSION_PROCESSOR_FUNCTION_NAME ?? "";
const INBOUND_LOCAL_PARTS = parseLocalParts(process.env.PAPYRUS_INBOUND_EMAIL_LOCAL_PARTS ?? "submissions,suggestions");
const INBOUND_DOMAIN = (process.env.PAPYRUS_INBOUND_EMAIL_DOMAIN ?? "p.apyr.us").trim().toLowerCase();
const MEDIA_BUCKET_NAME = (process.env.PAPYRUS_MEDIA_BUCKET_NAME ?? "").trim();

const s3Client = new S3Client({});
const lambdaClient = new LambdaClient({});

type InboundPayload = {
  senderEmail: string;
  recipients: string[];
  subject: string;
  bodyText: string;
  citations: Array<Record<string, unknown>>;
  s3Bucket: string | null;
  s3Key: string | null;
  sesMessageId: string | null;
  inReplyTo: string | null;
  references: string | null;
  attachmentCount: number;
  userComposedText: string;
  parentSubmissionMessageId: string | null;
};

type ExistingMessage = {
  id: string;
  status?: string | null;
  responseStatus?: string | null;
  metadata?: unknown;
};

export const handler = async (event: Record<string, unknown>) => {
  if (event.source === "papyrus.inbound-email" && event.action === "retry-pending") {
    return retryPendingInboundMime();
  }

  const inbound = await resolveInboundPayload(event);
  if (inbound.s3Key && !shouldProcessInboundS3Key(inbound.s3Key)) {
    return { ok: true, skipped: true, reason: "inbound-s3-key-not-eligible", s3Key: inbound.s3Key };
  }

  return processInboundSubmission(inbound);
};

async function retryPendingInboundMime(): Promise<Record<string, unknown>> {
  if (!MEDIA_BUCKET_NAME) {
    throw new Error("PAPYRUS_MEDIA_BUCKET_NAME is not configured for inbound email retry.");
  }

  const results: Array<Record<string, unknown>> = [];
  let continuationToken: string | undefined;
  do {
    const listing = await s3Client.send(new ListObjectsV2Command({
      Bucket: MEDIA_BUCKET_NAME,
      Prefix: "inbound-email/",
      ContinuationToken: continuationToken,
      MaxKeys: 100,
    }));
    for (const entry of listing.Contents ?? []) {
      const key = entry.Key ?? "";
      if (!shouldProcessInboundS3Key(key)) continue;
      try {
        const inbound = await loadInboundFromS3Object(MEDIA_BUCKET_NAME, key, sesMessageIdFromObjectKey(key));
        results.push(await processInboundSubmission(inbound));
      } catch (error) {
        results.push({
          ok: false,
          s3Key: key,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
    continuationToken = listing.IsTruncated ? listing.NextContinuationToken : undefined;
  } while (continuationToken);

  return { ok: true, action: "retry-pending", processedCount: results.length, results };
}

async function processInboundSubmission(inbound: InboundPayload): Promise<Record<string, unknown>> {
  const recipientEmail = inbound.recipients.find((entry) => isConfiguredInboundAddress(entry)) ?? inbound.recipients[0] ?? "";
  if (!isConfiguredInboundAddress(recipientEmail)) {
    throw new Error(`Inbound email recipient ${recipientEmail || "(missing)"} is not configured for this environment.`);
  }

  const messageId = inbound.s3Bucket && inbound.s3Key
    ? inboundMessageIdFromS3(inbound.s3Bucket, inbound.s3Key)
    : null;
  const existing = messageId ? await getExistingInboundMessage(messageId) : null;
  if (existing) {
    return resumeExistingInboundSubmission(existing, inbound, recipientEmail);
  }

  const now = new Date().toISOString();
  const resolvedMessageId = messageId ?? `message-email-submission-${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
  const dataClient = await getLambdaDataClient();
  const profileId = await lookupRegisteredUserProfileId(dataClient, inbound.senderEmail);
  const authorized = Boolean(profileId);
  const citations = authorized
    ? (inbound.citations.length > 0
      ? inbound.citations
      : extractDirectCitations(inbound.bodyText) as Array<Record<string, unknown>>)
    : [];
  const intakeClassification = classifyInboundEmailIntake({
    bodyText: inbound.bodyText,
    citations,
    parentSubmissionMessageId: inbound.parentSubmissionMessageId,
    attachmentCount: inbound.attachmentCount,
    userComposedText: inbound.userComposedText,
  });
  const attachmentOnlyReply = intakeClassification === "attachment_only_reply";
  const conversationalReply = intakeClassification === "conversational_reply";
  const agentIntake = intakeClassification === "agent_intake";
  const pdfOnlyIntake = intakeClassification === "pdf_only_intake";

  let status = authorized ? "received" : "rejected";
  let responseStatus = authorized ? "PENDING" : "REJECTED";
  let responseError: string | null = authorized ? null : UNREGISTERED_SENDER_RESPONSE_ERROR;

  if (authorized && looksLikeResearchAssignmentRequest(inbound.bodyText, citations.length)) {
    status = "rejected";
    responseStatus = "REJECTED";
    responseError = "Submission looks like a research assignment request. Send direct citations (URLs or DOIs), not open-ended research tasks.";
  } else if (
    authorized
    && citations.length === 0
    && !attachmentOnlyReply
    && !conversationalReply
    && !agentIntake
    && !pdfOnlyIntake
  ) {
    status = "rejected";
    responseStatus = "REJECTED";
    responseError = "No direct citations (URL or DOI) were found in the email body.";
  }

  const messageInput = buildEmailSubmissionMessageInput({
    id: resolvedMessageId,
    now,
    subject: inbound.subject,
    bodyText: inbound.bodyText,
    senderEmail: inbound.senderEmail,
    recipientEmail,
    sesMessageId: inbound.sesMessageId,
    s3Bucket: inbound.s3Bucket,
    s3Key: inbound.s3Key,
    authorized,
    authorUserProfileId: profileId,
    authorLabel: inbound.senderEmail || "unknown-sender",
    citations,
    status,
    responseStatus,
    responseError,
    parentSubmissionMessageId: inbound.parentSubmissionMessageId,
    intakeClassification,
    inboundInReplyTo: inbound.inReplyTo,
    inboundReferences: inbound.references,
    inboundAttachmentCount: inbound.attachmentCount,
  });

  const createResponse = await dataClient.models.Message.create(
    messageInput as never,
    { authMode: LAMBDA_DATA_AUTH_MODE },
  );
  if (createResponse.errors?.length) {
    const messages = createResponse.errors.map((entry) => entry?.message ?? String(entry)).join("; ");
    throw new Error(`Failed to create inbound email submission message: ${messages}`);
  }
  await putTextModelPayload(
    dataClient as any,
    { ownerKind: "message", ownerId: resolvedMessageId, ownerLineageId: resolvedMessageId },
    "message_body",
    "message",
    inbound.bodyText,
    { filename: "message.txt", mediaType: "text/plain", now },
  );

  if (authorized && responseStatus === "PENDING" && PROCESSOR_FUNCTION_NAME) {
    await invokeEmailProcessor(resolvedMessageId);
  } else if (responseStatus === "REJECTED" && PROCESSOR_FUNCTION_NAME) {
    await invokeEmailProcessor(resolvedMessageId, { sendFeedbackOnly: true });
  }

  return {
    ok: true,
    messageId: resolvedMessageId,
    authorized,
    status,
    responseStatus,
    directCitationCount: citations.length,
    recipientEmail,
    senderEmail: inbound.senderEmail,
    idempotent: false,
  };
}

async function resumeExistingInboundSubmission(
  existing: ExistingMessage,
  inbound: InboundPayload,
  recipientEmail: string,
): Promise<Record<string, unknown>> {
  const metadata = parseMessageMetadata(existing.metadata);
  const authorized = metadata.authorized === true;
  const responseStatus = String(existing.responseStatus ?? metadata.responseStatus ?? "").toUpperCase();

  if (responseStatus === "COMPLETED") {
    const feedbackDeferred = metadata.feedbackEmailDeferred === true && !metadata.feedbackEmailSentAt;
    if (feedbackDeferred && PROCESSOR_FUNCTION_NAME) {
      await invokeEmailProcessor(existing.id, { sendFeedbackOnly: true });
      return {
        ok: true,
        messageId: existing.id,
        idempotent: true,
        alreadyProcessed: true,
        reattemptedDeferredFeedback: true,
        recipientEmail,
        senderEmail: inbound.senderEmail,
      };
    }
    return {
      ok: true,
      messageId: existing.id,
      idempotent: true,
      alreadyProcessed: true,
      recipientEmail,
      senderEmail: inbound.senderEmail,
    };
  }

  if (authorized && (responseStatus === "PENDING" || responseStatus === "FAILED" || responseStatus === "IN_PROGRESS")) {
    if (PROCESSOR_FUNCTION_NAME) {
      await invokeEmailProcessor(existing.id);
    }
    return {
      ok: true,
      messageId: existing.id,
      idempotent: true,
      reprocessed: true,
      responseStatus,
      recipientEmail,
      senderEmail: inbound.senderEmail,
    };
  }

  const responseError = String(metadata.responseError ?? "").toLowerCase();
  const falseNoCitationRejection = responseStatus === "REJECTED"
    && responseError.includes("no direct citations")
    && inbound.citations.length > 0;
  if (authorized && falseNoCitationRejection) {
    if (PROCESSOR_FUNCTION_NAME) {
      await invokeEmailProcessor(existing.id);
    }
    return {
      ok: true,
      messageId: existing.id,
      idempotent: true,
      reprocessed: true,
      correctedCitations: true,
      directCitationCount: inbound.citations.length,
      responseStatus,
      recipientEmail,
      senderEmail: inbound.senderEmail,
    };
  }

  return {
    ok: true,
    messageId: existing.id,
    idempotent: true,
    skipped: true,
    responseStatus,
    recipientEmail,
    senderEmail: inbound.senderEmail,
  };
}

async function getExistingInboundMessage(messageId: string): Promise<ExistingMessage | null> {
  const client = await getLambdaDataClient();
  const response = await client.models.Message.get(
    { id: messageId },
    { authMode: LAMBDA_DATA_AUTH_MODE },
  );
  if (response.errors?.length) {
    const messages = response.errors.map((entry) => entry?.message ?? String(entry)).join("; ");
    throw new Error(`Failed to load inbound email submission message: ${messages}`);
  }
  return (response.data as ExistingMessage | null) ?? null;
}

async function invokeEmailProcessor(
  messageId: string,
  options: { sendFeedbackOnly?: boolean } = {},
): Promise<void> {
  await lambdaClient.send(new InvokeCommand({
    FunctionName: PROCESSOR_FUNCTION_NAME,
    InvocationType: "Event",
    Payload: Buffer.from(JSON.stringify({
      messageId,
      corpusKey: process.env.PAPYRUS_INBOUND_EMAIL_CORPUS_KEY ?? "AI-ML-research",
      ...(options.sendFeedbackOnly ? { sendFeedbackOnly: true } : {}),
    })),
  }));
}

async function resolveInboundPayload(event: Record<string, unknown>): Promise<InboundPayload> {
  if (event.source === "aws.s3" && event.detail && typeof event.detail === "object") {
    return resolveFromS3ObjectCreated(event.detail as Record<string, unknown>);
  }

  const record = Array.isArray(event.Records) ? event.Records[0] : null;
  if (record && typeof record === "object") {
    const s3Record = record as { s3?: { bucket?: { name?: string }; object?: { key?: string } }; ses?: { mail?: Record<string, unknown>; receipt?: Record<string, unknown> } };
    if (s3Record.s3) {
      const bucket = normalizeOptionalString(s3Record.s3.bucket?.name);
      const key = normalizeOptionalString(s3Record.s3.object?.key);
      if (bucket && key) {
        return loadInboundFromS3Object(bucket, key, null);
      }
    }

    const mail = s3Record.ses?.mail;
    if (mail && typeof mail === "object") {
      return resolveFromSesMail(mail, s3Record.ses?.receipt);
    }
  }

  throw new Error("Unsupported inbound email event payload.");
}

async function resolveFromS3ObjectCreated(detail: Record<string, unknown>): Promise<InboundPayload> {
  const bucketInfo = detail.bucket && typeof detail.bucket === "object" ? detail.bucket as Record<string, unknown> : {};
  const objectInfo = detail.object && typeof detail.object === "object" ? detail.object as Record<string, unknown> : {};
  const bucket = normalizeOptionalString(bucketInfo.name);
  const key = normalizeOptionalString(objectInfo.key);
  if (!bucket || !key) throw new Error("S3 Object Created event did not include bucket and object key.");
  return loadInboundFromS3Object(bucket, key, sesMessageIdFromObjectKey(key));
}

async function resolveFromSesMail(
  mail: Record<string, unknown>,
  receipt: Record<string, unknown> | undefined,
): Promise<InboundPayload> {
  const senderEmail = extractSenderFromSesMail(mail);
  const recipients = extractRecipientsFromSesMail(mail);
  const receiptData = receipt && typeof receipt === "object" ? receipt : {};
  const action = receiptData.action && typeof receiptData.action === "object" ? receiptData.action as Record<string, unknown> : {};
  const s3Bucket = normalizeOptionalString(action.bucketName);
  const s3Key = normalizeOptionalString(action.objectKey);
  const sesMessageId = normalizeOptionalString(mail.messageId);

  const headers = mail.commonHeaders && typeof mail.commonHeaders === "object"
    ? (mail.commonHeaders as Record<string, unknown>)
    : {};
  const subject = normalizeOptionalString(
    Array.isArray(headers.subject) ? headers.subject[0] : headers.subject,
  ) ?? "(no subject)";

  if (s3Bucket && s3Key) {
    const loaded = await loadInboundFromS3Object(s3Bucket, s3Key, sesMessageId);
    return {
      ...loaded,
      senderEmail: loaded.senderEmail || senderEmail,
      recipients: loaded.recipients.length > 0 ? loaded.recipients : recipients,
      subject: loaded.subject !== "(no subject)" ? loaded.subject : subject,
    };
  }

  return enrichInboundPayload({
    senderEmail,
    recipients,
    subject,
    bodyText: "",
    citations: [],
    s3Bucket,
    s3Key,
    sesMessageId,
    inReplyTo: null,
    references: null,
    attachmentCount: 0,
    userComposedText: "",
    parentSubmissionMessageId: null,
  });
}

async function loadInboundFromS3Object(
  bucket: string,
  key: string,
  sesMessageId: string | null,
): Promise<InboundPayload> {
  const rawObject = await s3Client.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
  const rawBytes = await streamToBuffer(rawObject.Body);
  const intake = parseInboundMimeForIntake(rawBytes);
  const threading = parseInboundMimeThreading(rawBytes);
  return enrichInboundPayload({
    senderEmail: extractSenderFromRawMime(rawBytes),
    recipients: extractRecipientsFromRawMime(rawBytes),
    subject: intake.subject || "(no subject)",
    bodyText: intake.bodyText,
    citations: intake.citations as Array<Record<string, unknown>>,
    s3Bucket: bucket,
    s3Key: key,
    sesMessageId,
    inReplyTo: threading.inReplyTo,
    references: threading.references,
    attachmentCount: countInboundAttachments(rawBytes),
    userComposedText: extractUserComposedReplyText(intake.bodyText),
    parentSubmissionMessageId: null,
  });
}

function enrichInboundPayload(payload: InboundPayload): InboundPayload {
  const parentSubmissionMessageId = payload.parentSubmissionMessageId
    ?? resolveParentSubmissionMessageId(payload.inReplyTo, payload.references);
  return {
    ...payload,
    parentSubmissionMessageId,
    userComposedText: payload.userComposedText || extractUserComposedReplyText(payload.bodyText),
  };
}

function sesMessageIdFromObjectKey(key: string): string | null {
  const basename = key.split("/").pop() ?? "";
  const match = basename.match(/^[A-Za-z0-9_-]+$/);
  return match ? basename : null;
}

function isConfiguredInboundAddress(address: string): boolean {
  const normalized = normalizeEmailAddress(address);
  if (!normalized.includes("@")) return false;
  const [localPart, domain] = normalized.split("@", 2);
  return domain === INBOUND_DOMAIN && INBOUND_LOCAL_PARTS.includes(localPart);
}

function parseLocalParts(value: string): string[] {
  return value
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
}

function normalizeOptionalString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

async function streamToBuffer(body: unknown): Promise<Uint8Array> {
  if (!body) return new Uint8Array();
  if (body instanceof Uint8Array) return body;
  if (typeof (body as { transformToByteArray?: () => Promise<Uint8Array> }).transformToByteArray === "function") {
    return (body as { transformToByteArray: () => Promise<Uint8Array> }).transformToByteArray();
  }
  const chunks: Uint8Array[] = [];
  for await (const chunk of body as AsyncIterable<Uint8Array>) {
    chunks.push(chunk);
  }
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}
