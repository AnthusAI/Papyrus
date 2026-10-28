import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";

export type ContentActionError = { code: string; message: string; line: number | null };

export type DeriveMarkusInput = { frontMatterYaml: string | null; bodyMarkus: string; includeIr?: boolean };
export type SaveItemDraftInput = {
  id: string | null;
  type: string;
  slug: string;
  section: string | null;
  frontMatterYaml: string | null;
  bodyMarkus: string;
  aliases: string[];
  expectedContentHash: string | null;
  /** Records a new draft version of the story instead of correcting the current one in place. */
  newVersion?: boolean;
  changeReason?: string | null;
};

export type DeriveMarkusResult = { ok: true; bodyIrBytes: number; bodyIr?: unknown; errors: [] };
export type SavedItemSummary = {
  id: string;
  contentHash: string;
  status: string;
  slug: string;
  versionNumber: number | null;
};
export type SaveItemDraftResult = { ok: true; item: SavedItemSummary };
export type PublishItemResult = { ok: true; changed: boolean; publishedId: string; versionNumber: number | null };
export type UnpublishItemResult = { ok: true; changed: boolean };

export type CaptureAssessment = "complete" | "incomplete" | "incorrect";
export type CorrectReferenceCaptureInput = {
  referenceId: string;
  /** The full corrected or pasted text. */
  text?: string;
  /** The id of a PDF the editor uploaded to this Reference (a ModelAttachment); the server reads its text. Sent instead of `text`. */
  pdfAttachmentId?: string;
  grobid?: Record<string, unknown>;
  /** Required with text; alone it is just a label on the capture. */
  assessment?: CaptureAssessment;
  note?: string;
};
export type CorrectReferenceCaptureResult = { ok: true; referenceId: string; status: string; edits: Array<{ sortKey?: string; via?: string }>; label: unknown; summaryStale: boolean };

export class ContentActionFailure extends Error {
  readonly errors: ContentActionError[];

  constructor(errors: ContentActionError[]) {
    super(errors.map((error) => error.message).join("; ") || "Content action failed");
    this.name = "ContentActionFailure";
    this.errors = errors;
  }
}

type GraphqlEnvelope = { data?: unknown; errors?: { message?: string }[] | null };

export type ContentActionsTransport = {
  queries: { deriveMarkus: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope> };
  mutations: {
    saveItemDraft: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
    publishItem: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
    unpublishItem: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
    correctReferenceCapture: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
  };
};

const USER_POOL = { authMode: "userPool" } as const;

function parseActionResponse<T>(envelope: GraphqlEnvelope): T {
  if (envelope.errors && envelope.errors.length > 0) {
    throw new Error(envelope.errors.map((error) => error.message ?? "GraphQL error").join("; "));
  }
  const raw = envelope.data;
  const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!parsed || typeof parsed !== "object") {
    throw new Error("The content action returned no data.");
  }
  const response = parsed as { ok?: boolean; errors?: ContentActionError[] };
  if (response.ok !== true) {
    throw new ContentActionFailure(response.errors ?? []);
  }
  return parsed as T;
}

export function createContentActionsClient(transport: ContentActionsTransport) {
  return {
    async deriveMarkus(input: DeriveMarkusInput): Promise<DeriveMarkusResult> {
      return parseActionResponse(await transport.queries.deriveMarkus({ input: JSON.stringify(input) }, USER_POOL));
    },
    async saveItemDraft(input: SaveItemDraftInput): Promise<SaveItemDraftResult> {
      return parseActionResponse(await transport.mutations.saveItemDraft({ input: JSON.stringify(input) }, USER_POOL));
    },
    async publishItem(id: string): Promise<PublishItemResult> {
      return parseActionResponse(await transport.mutations.publishItem({ input: JSON.stringify({ id }) }, USER_POOL));
    },
    async correctReferenceCapture(input: CorrectReferenceCaptureInput): Promise<CorrectReferenceCaptureResult> {
      return parseActionResponse(await transport.mutations.correctReferenceCapture({ input: JSON.stringify(input) }, USER_POOL));
    },
    async unpublishItem(id: string): Promise<UnpublishItemResult> {
      return parseActionResponse(await transport.mutations.unpublishItem({ input: JSON.stringify({ id }) }, USER_POOL));
    },
  };
}

let defaultClient: ReturnType<typeof createContentActionsClient> | null = null;

function contentActionsClient() {
  if (!defaultClient) {
    defaultClient = createContentActionsClient(generateClient<Schema>() as unknown as ContentActionsTransport);
  }
  return defaultClient;
}

export const deriveMarkus = (input: DeriveMarkusInput) => contentActionsClient().deriveMarkus(input);
export const saveItemDraft = (input: SaveItemDraftInput) => contentActionsClient().saveItemDraft(input);
export const publishItem = (id: string) => contentActionsClient().publishItem(id);
export const unpublishItem = (id: string) => contentActionsClient().unpublishItem(id);

export const correctReferenceCapture = (input: CorrectReferenceCaptureInput) => contentActionsClient().correctReferenceCapture(input);
