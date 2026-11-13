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
export type PublishItemResult = {
  ok: true;
  changed: boolean;
  publishedId: string;
  versionNumber: number | null;
  /** The projection built no page for this Item: its type has no `urls.types` entry and its section no route. Published is recorded; nothing is live. */
  noPublicPage?: boolean;
  /** The Story was live as this type and was published as another: its address moved, and the old one redirects. */
  typeChangedFrom?: string;
  url?: string;
};
export type UnpublishItemResult = { ok: true; changed: boolean };
export type MoveStoryStageInput = { lineageId: string; stage: string; reason?: string | null };
export type MoveStoryStageResult = { ok: true; changed: boolean; stage: string };

/**
 * Sets, changes or clears (`scheduledPublishAt: null`) the time a Story's version goes live: the `schedule` operation of the site's `scheduleItem` mutation
 * (docs/scheduled-publishing.md). `itemId` is the version being scheduled (the newest); clearing names the Story, whose schedule may sit on an earlier version. The
 * instant is UTC: the console turns the publication-zone time an editor picked into it (lib/story-schedule.ts), so the backend never has to read a wall-clock time.
 */
export type ScheduleStoryInput = { itemId: string; lineageId: string; scheduledPublishAt: string | null };
export type ScheduleStoryResult = { ok: true; scheduledPublishAt: string | null; scheduledBy: string | null };

/**
 * One scheduled version in the `schedule_list` answer (`story_schedule.ScheduleService.entry`). `state` is the effective state (overdue when the time passed and it
 * has not published); `storedState` is what the row holds (scheduled, publishing or blocked). A one-Story read also says what the newest version is.
 */
export type ScheduleEntry = {
  itemId: string; lineageId: string; versionNumber: number | null; title: string;
  state: "scheduled" | "publishing" | "blocked" | "overdue"; storedState: "scheduled" | "publishing" | "blocked";
  scheduledPublishAt: string; scheduledBy: string | null; scheduledAt: string | null;
  headItemId?: string; headVersionNumber?: number | null; newerVersionExists?: boolean;
};
/** The `schedule_list` operation of `scheduleItem`: the schedules of one Story (`storyLineageId`), soonest first. */
export type ScheduleListResult = { ok: true; timeZone: string | null; schedules: ScheduleEntry[] };

/** The `schedule_settings` operation of `scheduleItem`: whether scheduling is on and the publication's time zone, which the backend owns (docs/scheduled-publishing.md). */
export type ScheduleZoneResult = { ok: true; enabled: boolean; timeZone: string | null };

export type CreateStoryFromReferenceInput = {
  referenceId: string;
  /** A Story type of the site. Omitted, the site's default type (`storyTypes.default`, else `article`). */
  itemType?: string;
  /** Make another story although this Reference already has one. */
  again?: boolean;
  /** Read only by the local preview, which has no backend to look the Reference up in; the real action ignores it. */
  preview?: { title: string; url: string | null; summary: string | null; imageUrl: string | null; site: string | null };
};
export type ExistingStory = { itemId: string; lineageId: string; title: string; stage: string | null };
export type CreateStoryFromReferenceResult =
  | {
      ok: true;
      created: true;
      itemId: string;
      lineageId: string;
      title: string;
      itemType: string;
      stage: string;
      /** `included`, `none` (the Reference had no summary) or `withheld` (it repeated the source's own words). */
      summary: "included" | "none" | "withheld";
      image: "seeded" | "none" | string;
      imageCredit: string | null;
    }
  | { ok: true; created: false; existing: ExistingStory[]; referenceLineageId: string };

/** A change to one checklist step of a Story (the sub-task Item of that step): done, skipped, not applicable, or open again. With no `state` and a `note` it adds a note to the step and changes nothing else. The backend stamps the signed-in person. */
export type SetStoryStepInput = { lineageId: string; stepKey: string; state?: "open" | "done" | "skipped" | "not_applicable"; reason?: string; note?: string };
export type SetStoryStepResult = { ok: true; step: { stepKey: string; state: string; changedAt?: string | null } };

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
    moveStoryStage: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
    setStoryStep: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
    scheduleItem: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
    createStoryFromReference: (args: { input: string }, options: { authMode: "userPool" }) => Promise<GraphqlEnvelope>;
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
    async moveStoryStage(input: MoveStoryStageInput): Promise<MoveStoryStageResult> {
      return parseActionResponse(await transport.mutations.moveStoryStage({ input: JSON.stringify(input) }, USER_POOL));
    },
    async scheduleStory(input: ScheduleStoryInput): Promise<ScheduleStoryResult> {
      const operation = input.scheduledPublishAt === null
        ? { operation: "schedule", arguments: { storyLineageId: input.lineageId, clear: true } }
        : { operation: "schedule", arguments: { itemId: input.itemId, at: input.scheduledPublishAt } };
      const result = parseActionResponse<{ scheduledPublishAt?: string; scheduledBy?: string }>(await transport.mutations.scheduleItem({ input: JSON.stringify(operation) }, USER_POOL));
      return { ok: true, scheduledPublishAt: result.scheduledPublishAt ?? null, scheduledBy: result.scheduledBy ?? null };
    },
    async scheduleList(input: { storyLineageId: string }): Promise<ScheduleListResult> {
      const result = parseActionResponse<{ timeZone?: string | null; schedules?: ScheduleEntry[] }>(await transport.mutations.scheduleItem({ input: JSON.stringify({ operation: "schedule_list", arguments: { storyLineageId: input.storyLineageId } }) }, USER_POOL));
      return { ok: true, timeZone: result.timeZone ?? null, schedules: result.schedules ?? [] };
    },
    async scheduleZone(): Promise<ScheduleZoneResult> {
      const result = parseActionResponse<{ enabled: boolean; timeZone?: string | null }>(await transport.mutations.scheduleItem({ input: JSON.stringify({ operation: "schedule_settings", arguments: {} }) }, USER_POOL));
      return { ok: true, enabled: result.enabled, timeZone: result.timeZone ?? null };
    },
    async setStoryStep(input: SetStoryStepInput): Promise<SetStoryStepResult> {
      return parseActionResponse(await transport.mutations.setStoryStep({ input: JSON.stringify(input) }, USER_POOL));
    },
    async createStoryFromReference(input: CreateStoryFromReferenceInput): Promise<CreateStoryFromReferenceResult> {
      const { preview: _preview, ...sent } = input;
      return parseActionResponse(await transport.mutations.createStoryFromReference({ input: JSON.stringify(sent) }, USER_POOL));
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
export const createStoryFromReference = (input: CreateStoryFromReferenceInput) => contentActionsClient().createStoryFromReference(input);
export const moveStoryStage = (input: MoveStoryStageInput) => contentActionsClient().moveStoryStage(input);
export const scheduleStory = (input: ScheduleStoryInput) => contentActionsClient().scheduleStory(input);
export const scheduleList = (input: { storyLineageId: string }) => contentActionsClient().scheduleList(input);
export const scheduleZone = () => contentActionsClient().scheduleZone();
export const setStoryStep = (input: SetStoryStepInput) => contentActionsClient().setStoryStep(input);
export const unpublishItem = (id: string) => contentActionsClient().unpublishItem(id);

export const correctReferenceCapture = (input: CorrectReferenceCaptureInput) => contentActionsClient().correctReferenceCapture(input);
