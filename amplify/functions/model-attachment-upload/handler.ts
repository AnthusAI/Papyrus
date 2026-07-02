import { createHash } from "node:crypto";
import { DeleteObjectCommand, GetObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";

type CreateUploadHandler = Schema["createModelAttachmentUpload"]["functionHandler"];
type CompleteUploadHandler = Schema["completeModelAttachmentUpload"]["functionHandler"];
type AbortUploadHandler = Schema["abortModelAttachmentUpload"]["functionHandler"];
type CreateDownloadHandler = Schema["createModelAttachmentDownload"]["functionHandler"];
type UploadEvent =
  | Parameters<CreateUploadHandler>[0]
  | Parameters<CompleteUploadHandler>[0]
  | Parameters<AbortUploadHandler>[0]
  | Parameters<CreateDownloadHandler>[0];
type DataClient = ReturnType<typeof generateClient<Schema>>;
type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;

const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;
const MAX_GRAPH_EXPORT_ATTACHMENT_BYTES = 512 * 1024 * 1024;
const UPLOAD_EXPIRES_SECONDS = 10 * 60;
const DOWNLOAD_EXPIRES_SECONDS = 10 * 60;
const ALLOWED_OWNER_KINDS = new Set([
  "assignment",
  "assignmentEvent",
  "item",
  "knowledgeRawPayload",
  "message",
  "publishedItem",
  "procedureVersion",
  "reference",
  "semanticNode",
  "semanticRelation",
]);
const ALLOWED_ROLES = new Set([
  "assignment_brief",
  "assignment_instructions",
  "item_body",
  "item_excerpt",
  "message_body",
  "metadata",
  "ontology_concept_profile",
  "ontology_relation_explanation",
  "published_item_body",
  "published_item_excerpt",
  "code",
  "graph_export",
  "raw_payload",
]);
const ALLOWED_MEDIA_TYPES = new Set([
  "application/json",
  "application/gzip",
  "application/x-ndjson",
  "text/csv",
  "text/markdown",
  "text/plain",
  "text/tab-separated-values",
]);

const s3 = new S3Client({});
let clientPromise: Promise<DataClient> | null = null;

export const handler = async (event: UploadEvent) => {
  const fieldName = normalizeRequiredString(event.info?.fieldName ?? (event as { fieldName?: string | null }).fieldName, "fieldName");
  if (fieldName === "createModelAttachmentUpload") return createModelAttachmentUpload(event as Parameters<CreateUploadHandler>[0]);
  if (fieldName === "completeModelAttachmentUpload") return completeModelAttachmentUpload(event as Parameters<CompleteUploadHandler>[0]);
  if (fieldName === "abortModelAttachmentUpload") return abortModelAttachmentUpload(event as Parameters<AbortUploadHandler>[0]);
  if (fieldName === "createModelAttachmentDownload") return createModelAttachmentDownload(event as Parameters<CreateDownloadHandler>[0]);
  throw new Error(`Unsupported model attachment upload action ${fieldName}.`);
};

async function createModelAttachmentUpload(event: Parameters<CreateUploadHandler>[0]) {
  const input = normalizeAttachmentInput(event.arguments);
  await assertOwnerExists(input.ownerKind, input.ownerId);
  const put = new PutObjectCommand({
    Bucket: payloadBucketName(),
    Key: input.storagePath,
    ContentType: input.mediaType,
  });
  const uploadUrl = await getSignedUrl(s3, put, { expiresIn: UPLOAD_EXPIRES_SECONDS });
  const expiresAt = new Date(Date.now() + UPLOAD_EXPIRES_SECONDS * 1000).toISOString();
  const requiredHeaders: Record<string, string> = { "content-type": input.mediaType };
  return {
    ok: true,
    uploadId: uploadIdFor(input),
    attachmentId: input.id,
    ownerKind: input.ownerKind,
    ownerId: input.ownerId,
    role: input.role,
    sortKey: input.sortKey,
    method: "PUT",
    uploadUrl,
    storagePath: input.storagePath,
    mediaType: input.mediaType,
    byteSize: input.byteSize,
    sha256: input.sha256,
    expiresAt,
    requiredHeaders,
  };
}

async function completeModelAttachmentUpload(event: Parameters<CompleteUploadHandler>[0]) {
  const input = normalizeAttachmentInput(event.arguments);
  assertUploadId(event.arguments.uploadId, input);
  await assertOwnerExists(input.ownerKind, input.ownerId);
  const head = await s3.send(new HeadObjectCommand({
    Bucket: payloadBucketName(),
    Key: input.storagePath,
    ChecksumMode: "ENABLED",
  }));
  if (typeof head.ContentLength === "number" && head.ContentLength !== input.byteSize) {
    throw new Error(`Uploaded payload size mismatch for ${input.storagePath}: expected ${input.byteSize}, got ${head.ContentLength}.`);
  }
  const actualMediaType = normalizeOptionalString(head.ContentType)?.split(";")[0].trim().toLowerCase() ?? null;
  if (actualMediaType && actualMediaType !== input.mediaType) {
    throw new Error(`Uploaded payload media type mismatch for ${input.storagePath}: expected ${input.mediaType}, got ${actualMediaType}.`);
  }
  if (input.sha256) {
    const actualChecksum = await readObjectSha256(input.storagePath);
    if (actualChecksum !== input.sha256) {
      throw new Error(`Uploaded payload checksum mismatch for ${input.storagePath}.`);
    }
  }
  const now = new Date().toISOString();
  const client = await getDataClient();
  const current = await client.models.ModelAttachment.get({ id: input.id });
  assertNoDataErrors(current.errors, "get ModelAttachment");
  const record = {
    id: input.id,
    ownerKind: input.ownerKind,
    ownerId: input.ownerId,
    ownerLineageId: input.ownerLineageId,
    ownerVersionNumber: input.ownerVersionNumber,
    ownerVersionKey: input.ownerVersionKey,
    role: input.role,
    sortKey: input.sortKey,
    storagePath: input.storagePath,
    filename: input.filename,
    mediaType: input.mediaType,
    byteSize: input.byteSize,
    sha256: input.sha256,
    etag: normalizeOptionalString(head.ETag)?.replace(/^"|"$/g, "") ?? null,
    importRunId: input.importRunId,
    createdAt: current.data?.createdAt ?? now,
    updatedAt: now,
    status: input.status,
  };
  if (current.data) {
    await requireDataResult(client.models.ModelAttachment.update(record), "update ModelAttachment");
  } else {
    await requireDataResult(client.models.ModelAttachment.create(record), "create ModelAttachment");
  }
  return record;
}

async function abortModelAttachmentUpload(event: Parameters<AbortUploadHandler>[0]) {
  const input = normalizeAttachmentInput(event.arguments);
  assertUploadId(event.arguments.uploadId, input);
  await assertOwnerExists(input.ownerKind, input.ownerId);
  await s3.send(new DeleteObjectCommand({
    Bucket: payloadBucketName(),
    Key: input.storagePath,
  }));
  return {
    ok: true,
    uploadId: event.arguments.uploadId,
    attachmentId: input.id,
    storagePath: input.storagePath,
    status: "aborted",
  };
}

async function createModelAttachmentDownload(event: Parameters<CreateDownloadHandler>[0]) {
  const attachmentId = normalizeRequiredString(event.arguments.attachmentId, "attachmentId");
  const client = await getDataClient();
  const result = await client.models.ModelAttachment.get({ id: attachmentId });
  assertNoDataErrors(result.errors, "get ModelAttachment");
  const attachment = result.data;
  if (!attachment) throw new Error(`ModelAttachment ${attachmentId} was not found.`);
  const storagePath = normalizeRequiredString(attachment.storagePath, "storagePath");
  if (!storagePath.startsWith("newsroom/payloads/") && !storagePath.startsWith("media/payloads/")) {
    throw new Error(`ModelAttachment ${attachmentId} is not a supported payload attachment.`);
  }
  if (attachment.status && attachment.status !== "active") {
    throw new Error(`ModelAttachment ${attachmentId} is ${attachment.status}, not active.`);
  }
  const get = new GetObjectCommand({
    Bucket: payloadBucketName(),
    Key: storagePath,
  });
  const downloadUrl = await getSignedUrl(s3, get, { expiresIn: DOWNLOAD_EXPIRES_SECONDS });
  return {
    ok: true,
    attachmentId,
    method: "GET",
    downloadUrl,
    storagePath,
    mediaType: normalizeRequiredString(attachment.mediaType, "mediaType"),
    byteSize: attachment.byteSize ?? 0,
    sha256: attachment.sha256 ?? null,
    expiresAt: new Date(Date.now() + DOWNLOAD_EXPIRES_SECONDS * 1000).toISOString(),
    requiredHeaders: {},
  };
}

async function assertOwnerExists(ownerKind: string, ownerId: string): Promise<void> {
  const client = await getDataClient();
  const modelName = ownerModelName(ownerKind);
  const result = await (client.models as any)[modelName].get({ id: ownerId });
  assertNoDataErrors(result.errors, `get ${modelName}`);
  if (!result.data) throw new Error(`Cannot attach payload to missing ${modelName} ${ownerId}.`);
}

function normalizeAttachmentInput(input: Record<string, unknown>) {
  const ownerKind = normalizeRequiredString(input.ownerKind, "ownerKind");
  if (!ALLOWED_OWNER_KINDS.has(ownerKind)) throw new Error(`Unsupported ModelAttachment ownerKind ${ownerKind}.`);
  const ownerId = normalizeRequiredString(input.ownerId, "ownerId");
  const role = normalizeRequiredString(input.role, "role");
  if (!ALLOWED_ROLES.has(role)) throw new Error(`Unsupported ModelAttachment role ${role}.`);
  const sortKey = normalizeOptionalString(input.sortKey) ?? role;
  const filename = normalizeFilename(input.filename);
  const mediaType = normalizeRequiredString(input.mediaType, "mediaType").toLowerCase();
  if (!ALLOWED_MEDIA_TYPES.has(mediaType)) throw new Error(`Unsupported ModelAttachment mediaType ${mediaType}.`);
  const byteSize = normalizeByteSize(input.byteSize, role);
  const sha256 = normalizeSha256(input.sha256);
  const id = modelAttachmentId(ownerKind, ownerId, role, sortKey);
  const storagePath = modelPayloadStoragePath(ownerKind, ownerId, role, filename);
  return {
    id,
    ownerKind,
    ownerId,
    ownerLineageId: normalizeOptionalString(input.ownerLineageId),
    ownerVersionNumber: normalizeOptionalInteger(input.ownerVersionNumber),
    ownerVersionKey: normalizeOptionalString(input.ownerVersionKey),
    role,
    sortKey,
    storagePath,
    filename,
    mediaType,
    byteSize,
    sha256,
    importRunId: normalizeOptionalString(input.importRunId),
    status: normalizeOptionalString(input.status) ?? "active",
  };
}

function assertUploadId(value: unknown, input: ReturnType<typeof normalizeAttachmentInput>): void {
  const actual = normalizeRequiredString(value, "uploadId");
  const expected = uploadIdFor(input);
  if (actual !== expected) throw new Error("ModelAttachment uploadId does not match the requested attachment slot.");
}

function uploadIdFor(input: ReturnType<typeof normalizeAttachmentInput>): string {
  const fingerprint = [
    input.ownerKind,
    input.ownerId,
    input.role,
    input.sortKey,
    input.filename,
    input.mediaType,
    input.byteSize,
    input.sha256 ?? "",
  ].join("\n");
  return `model-attachment-upload-${createHash("sha256").update(fingerprint).digest("hex").slice(0, 32)}`;
}

function ownerModelName(ownerKind: string): string {
  if (ownerKind === "assignment") return "Assignment";
  if (ownerKind === "assignmentEvent") return "AssignmentEvent";
  if (ownerKind === "item") return "Item";
  if (ownerKind === "knowledgeRawPayload") return "KnowledgeRawPayload";
  if (ownerKind === "message") return "Message";
  if (ownerKind === "publishedItem") return "PublishedItem";
  if (ownerKind === "procedureVersion") return "ProcedureVersion";
  if (ownerKind === "reference") return "Reference";
  if (ownerKind === "semanticNode") return "SemanticNode";
  if (ownerKind === "semanticRelation") return "SemanticRelation";
  throw new Error(`Unsupported ModelAttachment ownerKind ${ownerKind}.`);
}

async function getDataClient(): Promise<DataClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const { resourceConfig, libraryOptions } = await getAmplifyDataClientConfig(process.env as never);
      Amplify.configure(resourceConfig, libraryOptions);
      return generateClient<Schema>();
    })();
  }
  return clientPromise;
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

function normalizeFilename(value: unknown): string {
  const filename = normalizeRequiredString(value, "filename");
  if (filename.includes("/") || filename.includes("\\") || filename === "." || filename === "..") {
    throw new Error("ModelAttachment filename must be a simple basename.");
  }
  if (!/^[A-Za-z0-9._-]+$/.test(filename)) throw new Error("ModelAttachment filename contains unsupported characters.");
  return filename;
}

function normalizeByteSize(value: unknown, role: string): number {
  const size = Number(value);
  if (!Number.isInteger(size) || size < 0) throw new Error("ModelAttachment byteSize must be a non-negative integer.");
  const maxBytes = role === "graph_export" ? MAX_GRAPH_EXPORT_ATTACHMENT_BYTES : MAX_ATTACHMENT_BYTES;
  if (size > maxBytes) throw new Error(`ModelAttachment byteSize exceeds ${maxBytes} bytes for role ${role}.`);
  return size;
}

function normalizeOptionalInteger(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) throw new Error("Expected integer value.");
  return parsed;
}

function normalizeSha256(value: unknown): string | null {
  const normalized = normalizeOptionalString(value);
  if (!normalized) return null;
  if (!/^[a-f0-9]{64}$/i.test(normalized)) throw new Error("ModelAttachment sha256 must be a 64-character hex digest.");
  return normalized.toLowerCase();
}

async function readObjectSha256(storagePath: string): Promise<string> {
  const result = await s3.send(new GetObjectCommand({
    Bucket: payloadBucketName(),
    Key: storagePath,
  }));
  const hash = createHash("sha256");
  const body = result.Body as AsyncIterable<Uint8Array> | undefined;
  if (!body) return hash.digest("hex");
  for await (const chunk of body) hash.update(chunk);
  return hash.digest("hex");
}

function normalizeRequiredString(value: unknown, label: string): string {
  const normalized = normalizeOptionalString(value);
  if (!normalized) throw new Error(`Missing required ${label}.`);
  return normalized;
}

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

async function requireDataResult<T>(promise: Promise<{ data?: T | null; errors?: DataClientErrors }>, context: string): Promise<T | null | undefined> {
  const result = await promise;
  assertNoDataErrors(result.errors, context);
  return result.data;
}

function assertNoDataErrors(errors: DataClientErrors, context: string): void {
  if (Array.isArray(errors) && errors.length) {
    throw new Error(`${context}: ${errors.map((error) => typeof error === "string" ? error : JSON.stringify(error)).join("; ")}`);
  }
}
