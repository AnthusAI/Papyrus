"use client";

/**
 * The newsroom's front end for the image-service door: `imageRead` for operations that only read, `imageWrite` for the ones that write. The door takes who is
 * asking from the signed-in session; the browser only says which operation and its input (docs/images.md). Pictures go up through the existing attachment upload.
 */
import { generateClient } from "aws-amplify/data";
import { configureAmplifyClient } from "../../components/amplify-client-provider";
import { uploadModelPayloadForOwner } from "../../components/news-desk-taxonomy-client";
import { callImageOperation, type ImageEnvelope, type ImageOperationName, type ImageOperations } from "./operations.generated";
import { extensionFor } from "./visual-style-admin";

export type ImageDoor = <Name extends ImageOperationName>(op: Name, input: ImageOperations[Name]["input"]) => Promise<ImageEnvelope<ImageOperations[Name]["result"]>>;
export type UploadExample = (file: File, kind: "exemplar" | "negative") => Promise<{ attachmentId: string }>;
export type ExampleUrl = (attachmentId: string) => Promise<string | null>;

const VISUAL_STYLE_OWNER_ID = "item-editorial-doctrine-visual-style";
const GRAPHQL_READ = `query ImageRead($op: String!, $input: AWSJSON) { imageRead(op: $op, input: $input) }`;
const GRAPHQL_WRITE = `mutation ImageWrite($op: String!, $input: AWSJSON, $requestId: ID!) { imageWrite(op: $op, input: $input, requestId: $requestId) }`;

export const imageDoor: ImageDoor = (op, input) => callImageOperation(op, input, async ({ op: name, input: body, effect }) => {
  configureAmplifyClient();
  const client = generateClient({ authMode: "userPool" });
  const payload = JSON.stringify(body ?? {});
  const response = (await client.graphql(effect === "read"
    ? { query: GRAPHQL_READ, variables: { op: name, input: payload } }
    : { query: GRAPHQL_WRITE, variables: { op: name, input: payload, requestId: crypto.randomUUID() } })) as { data?: Record<string, unknown>; errors?: { message?: string }[] };
  if (response.errors?.length) throw new Error(response.errors[0]?.message ?? "The image service could not be reached.");
  const raw = response.data?.[effect === "read" ? "imageRead" : "imageWrite"];
  return typeof raw === "string" ? JSON.parse(raw) : raw;
});

async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The picture is stored once, named by its own hash, under the profile's private item (the upload function enforces this). */
export const uploadExample: UploadExample = async (file, kind) => {
  const digest = await sha256Hex(file);
  const attachment = await uploadModelPayloadForOwner({
    ownerKind: "item", ownerId: VISUAL_STYLE_OWNER_ID, role: kind === "exemplar" ? "visual_example" : "visual_negative", sortKey: digest,
    filename: `${digest}.${extensionFor(file.type)}`, mediaType: file.type, content: file,
  });
  return { attachmentId: attachment.id };
};

const DOWNLOAD = `mutation CreateModelAttachmentDownload($attachmentId: ID!) { createModelAttachmentDownload(attachmentId: $attachmentId) { downloadUrl } }`;

export const exampleUrl: ExampleUrl = async (attachmentId) => {
  configureAmplifyClient();
  const client = generateClient({ authMode: "userPool" });
  const response = (await client.graphql({ query: DOWNLOAD, variables: { attachmentId } })) as { data?: { createModelAttachmentDownload?: { downloadUrl?: string | null } | null } };
  return response.data?.createModelAttachmentDownload?.downloadUrl ?? null;
};

