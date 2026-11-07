import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { setStoryStep } from "../lib/content-actions-client";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { addLocalPreviewStoryStepNote, createLocalPreviewStoryChecklist, setLocalPreviewStoryStep } from "../lib/local-preview-seed";
import { storyStepsFromItems, type StoryStepRecord, type StoryStepState, type SubTaskItemRecord } from "../lib/story-checklist";
import { configureAmplifyClient } from "./amplify-client-provider";

const STEPS_BY_PARENT_QUERY = `
  query ListItemsByParentAndOrder($parentLineageId: ID!, $limit: Int, $nextToken: String) {
    listItemsByParentAndOrder(parentLineageId: $parentLineageId, limit: $limit, nextToken: $nextToken) {
      items { id lineageId versionNumber type status title parentLineageId versionCreatedAt metadata }
      nextToken
    }
  }
`;

type Connection = { data?: { listItemsByParentAndOrder?: { items?: Array<SubTaskItemRecord | null> | null; nextToken?: string | null } | null } | null; errors?: { message?: string }[] | null };

/** The checklist steps of one Story: one read of the Item index by parent, made when the Story's panel opens (a board card reads the summary on the Story instead). */
export async function loadStoryChecklistSteps(lineageId: string): Promise<StoryStepRecord[]> {
  if (isLocalPreviewEnabled()) return createLocalPreviewStoryChecklist(lineageId);
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as { graphql: (options: Record<string, unknown>) => Promise<Connection> };
  const items: SubTaskItemRecord[] = [];
  let nextToken: string | null = null;
  do {
    const response: Connection = await client.graphql({ query: STEPS_BY_PARENT_QUERY, variables: { parentLineageId: lineageId, limit: 100, nextToken }, authMode: "userPool" });
    if (response.errors?.length) throw new Error(response.errors.map(error => error.message ?? "GraphQL error").join("; "));
    const connection = response.data?.listItemsByParentAndOrder;
    items.push(...((connection?.items ?? []).filter(Boolean) as SubTaskItemRecord[]));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return storyStepsFromItems(items);
}

/** Marks one step done, skipped, not applicable, or open again as the signed-in person; the backend writes the step's next version and the Story's summary. */
export async function saveStoryChecklistStep(lineageId: string, stepKey: string, state: StoryStepState, input: { reason?: string; note?: string }): Promise<void> {
  if (isLocalPreviewEnabled()) { setLocalPreviewStoryStep(lineageId, stepKey, state, input); return; }
  await setStoryStep({ lineageId, stepKey, state, ...(input.reason?.trim() ? { reason: input.reason.trim() } : {}), ...(input.note?.trim() ? { note: input.note.trim() } : {}) });
}

/** Adds a note to a step, whatever its state, as the signed-in person: notes only accumulate, and the step's state, reason and findings do not change. */
export async function addStoryChecklistNote(lineageId: string, stepKey: string, text: string): Promise<void> {
  if (isLocalPreviewEnabled()) { addLocalPreviewStoryStepNote(lineageId, stepKey, text); return; }
  await setStoryStep({ lineageId, stepKey, note: text.trim() });
}
