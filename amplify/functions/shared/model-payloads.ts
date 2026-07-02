import { createHash } from "node:crypto";
import { GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";

type DataClient = {
  models: {
    ModelAttachment: {
      get(input: { id: string }): Promise<{ data?: any | null; errors?: unknown }>;
      create(input: Record<string, unknown>): Promise<{ data?: any | null; errors?: unknown }>;
      update(input: Record<string, unknown>): Promise<{ data?: any | null; errors?: unknown }>;
    };
  };
};

const s3 = new S3Client({});

export type ModelPayloadOwner = {
  ownerKind: string;
  ownerId: string;
  ownerLineageId?: string | null;
  ownerVersionNumber?: number | null;
  ownerVersionKey?: string | null;
  importRunId?: string | null;
};

export async function putJsonModelPayload(
  client: DataClient,
  owner: ModelPayloadOwner,
  role: string,
  sortKey: string,
  payload: unknown,
  options: { filename?: string; now?: string; status?: string } = {},
) {
  const body = `${JSON.stringify(payload ?? {}, null, 2)}\n`;
  return putModelPayload(client, owner, role, sortKey, body, {
    filename: options.filename ?? `${safeId(sortKey || role)}.json`,
    mediaType: "application/json",
    now: options.now,
    status: options.status,
  });
}

export async function putTextModelPayload(
  client: DataClient,
  owner: ModelPayloadOwner,
  role: string,
  sortKey: string,
  body: string,
  options: { filename?: string; mediaType?: string; now?: string; status?: string } = {},
) {
  return putModelPayload(client, owner, role, sortKey, body, {
    filename: options.filename ?? `${safeId(sortKey || role)}.txt`,
    mediaType: options.mediaType ?? "text/plain",
    now: options.now,
    status: options.status,
  });
}

export async function putModelPayload(
  client: DataClient,
  owner: ModelPayloadOwner,
  role: string,
  sortKey: string,
  body: string,
  options: { filename: string; mediaType: string; now?: string; status?: string },
) {
  const now = options.now ?? new Date().toISOString();
  const storagePath = modelPayloadStoragePath(owner.ownerKind, owner.ownerId, role, options.filename);
  const buffer = Buffer.from(body, "utf8");
  const sha256 = createHash("sha256").update(buffer).digest("hex");
  await s3.send(new PutObjectCommand({
    Bucket: payloadBucketName(),
    Key: storagePath,
    Body: buffer,
    ContentType: options.mediaType,
  }));

  const id = modelAttachmentId(owner.ownerKind, owner.ownerId, role, sortKey);
  const input = {
    id,
    ownerKind: owner.ownerKind,
    ownerId: owner.ownerId,
    ownerLineageId: owner.ownerLineageId ?? null,
    ownerVersionNumber: owner.ownerVersionNumber ?? null,
    ownerVersionKey: owner.ownerVersionKey ?? null,
    role,
    sortKey,
    storagePath,
    filename: options.filename,
    mediaType: options.mediaType,
    byteSize: buffer.length,
    sha256,
    etag: null,
    importRunId: owner.importRunId ?? null,
    createdAt: now,
    updatedAt: now,
    status: options.status ?? "active",
  };
  const current = await client.models.ModelAttachment.get({ id });
  assertNoDataErrors(current.errors, "get ModelAttachment");
  if (current.data) {
    await requireDataResult(client.models.ModelAttachment.update({ ...input, createdAt: current.data.createdAt ?? now }), "update ModelAttachment");
  } else {
    await requireDataResult(client.models.ModelAttachment.create(input), "create ModelAttachment");
  }
  return input;
}

export async function readJsonModelPayload(
  client: DataClient,
  ownerKind: string,
  ownerId: string,
  role: string,
  sortKey = role,
) {
  const result = await client.models.ModelAttachment.get({ id: modelAttachmentId(ownerKind, ownerId, role, sortKey) });
  assertNoDataErrors(result.errors, "get ModelAttachment");
  const attachment = result.data;
  if (!attachment?.storagePath) return null;
  const text = await readTextFromStorage(attachment.storagePath);
  if (!text) return null;
  const parsed = JSON.parse(text);
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
}

async function readTextFromStorage(storagePath: string): Promise<string> {
  try {
    const result = await s3.send(new GetObjectCommand({
      Bucket: payloadBucketName(),
      Key: storagePath,
    }));
    return result.Body?.transformToString("utf8") ?? "";
  } catch (error) {
    if (isMissingStorageKeyError(error)) return "";
    throw error;
  }
}

function isMissingStorageKeyError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const record = error as Record<string, unknown>;
  if (record.name === "NoSuchKey" || record.Code === "NoSuchKey") return true;
  const message = typeof record.message === "string" ? record.message : "";
  return message.toLowerCase().includes("the specified key does not exist");
}

function payloadBucketName(): string {
  const bucket = process.env.papyrusMedia_BUCKET_NAME
    ?? process.env.PAPYRUS_MEDIA_BUCKET_NAME
    ?? process.env.STORAGE_BUCKET_NAME
    ?? process.env.AMPLIFY_STORAGE_BUCKET_NAME;
  if (!bucket) throw new Error("Missing Papyrus storage bucket environment variable for model payload attachments.");
  return bucket;
}

function modelPayloadStoragePath(ownerKind: string, ownerId: string, role: string, filename: string): string {
  const rootPrefix = ownerKind === "publishedItem" ? "media/payloads" : "newsroom/payloads";
  return `${rootPrefix}/${safeId(ownerKind)}/${safeId(ownerId)}/${safeId(role)}/${filename}`;
}

function modelAttachmentId(ownerKind: string, ownerId: string, role: string, sortKey: string): string {
  return `model-attachment-${safeId(ownerKind)}-${safeId(ownerId)}-${safeId(role)}-${safeId(sortKey)}`;
}

function safeId(value: unknown): string {
  const raw = String(value ?? "payload").trim();
  const normalized = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "payload";
  if (normalized.length <= 80) return normalized;
  const digest = createHash("sha256").update(raw).digest("hex").slice(0, 12);
  return `${normalized.slice(0, 67).replace(/-+$/g, "")}-${digest}`;
}

async function requireDataResult<T>(promise: Promise<{ data?: T | null; errors?: unknown }>, context: string): Promise<T | null | undefined> {
  const result = await promise;
  assertNoDataErrors(result.errors, context);
  return result.data;
}

function assertNoDataErrors(errors: unknown, context: string): void {
  if (Array.isArray(errors) && errors.length) {
    throw new Error(`${context}: ${errors.map((error) => typeof error === "string" ? error : JSON.stringify(error)).join("; ")}`);
  }
}
