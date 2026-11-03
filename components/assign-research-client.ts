"use client";

import { fetchAuthSession } from "aws-amplify/auth";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { buildResearchAssignmentPlan, type ResearchAssignmentPlan } from "../lib/assign-research";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { recordLocalPreviewAssignment } from "../lib/local-preview-seed";
import { moveStoryStage } from "../lib/content-actions-client";
import { configureAmplifyClient } from "./amplify-client-provider";
import { uploadModelPayloadForOwner } from "./news-desk-taxonomy-client";

const USER_POOL = "userPool";

export type AssignResearchInput = { lineageId: string; storyTitle: string; sectionKey: string | null; stage: string | null; direction: string; demo?: boolean };
export type AssignResearchResult = { assignmentId: string; movedStory: boolean };

async function actorLabel(): Promise<string> {
  try {
    const session = await fetchAuthSession();
    const payload = session.tokens?.idToken?.payload ?? {};
    for (const claim of [payload.email, payload.name, payload["cognito:username"], payload.sub]) if (typeof claim === "string" && claim.trim()) return claim.trim();
  } catch { /* the label falls back below */ }
  return "Papyrus newsroom";
}

function assertNoErrors(errors?: unknown[] | null) {
  if (!errors?.length) return;
  throw new Error(errors.map(error => (error && typeof error === "object" && "message" in error ? String((error as { message?: unknown }).message) : String(error))).join("; "));
}

/**
 * Writes the research assignment in the order that leaves nothing half done for the worker: the Assignment row, then its instructions and metadata
 * attachments, then the first AssignmentEvent. The Assignment is `open` from the first write, but the worker reads the `metadata` attachment (the `reporter`
 * profile and the direction) before it takes the assignment, and an open assignment without that profile is left alone, so the order is safe. A Story at
 * the idea stage then moves to the assignment stage through the recorded move; that move failing does not undo the assignment, and the error says so.
 */
export async function assignResearch(input: AssignResearchInput): Promise<AssignResearchResult> {
  const demo = input.demo || isLocalPreviewEnabled();
  const plan: ResearchAssignmentPlan = buildResearchAssignmentPlan({ ...input, actorLabel: demo ? "You" : await actorLabel(), now: new Date() });
  if (demo) {
    recordLocalPreviewAssignment(input.lineageId, plan);
    return { assignmentId: plan.assignment.id, movedStory: plan.movesStoryToAssignment };
  }
  configureAmplifyClient();
  const models = generateClient<Schema>().models as unknown as Record<string, { create: (value: never, options: { authMode: string }) => Promise<{ errors?: unknown[] | null }> }>;
  assertNoErrors((await models.Assignment.create(plan.assignment as never, { authMode: USER_POOL })).errors);
  const owner = { ownerKind: "assignment", ownerId: plan.assignment.id, ownerLineageId: plan.assignment.id, status: "active" };
  await uploadModelPayloadForOwner({ ...owner, role: "assignment_instructions", sortKey: "instructions", filename: "instructions.txt", mediaType: "text/plain", content: plan.instructions });
  await uploadModelPayloadForOwner({ ...owner, role: "metadata", sortKey: "metadata", filename: "metadata.json", mediaType: "application/json", content: JSON.stringify(plan.metadata, null, 2) });
  assertNoErrors((await models.AssignmentEvent.create(plan.event as never, { authMode: USER_POOL })).errors);
  if (plan.movesStoryToAssignment) {
    try {
      await moveStoryStage({ lineageId: input.lineageId, stage: "assignment", reason: `Research assignment ${plan.assignment.id} created` });
    } catch (failure) {
      throw new Error(`The research assignment was created, but the Story could not be moved to the assignment stage: ${failure instanceof Error ? failure.message : "try moving it by hand."}`);
    }
  }
  return { assignmentId: plan.assignment.id, movedStory: plan.movesStoryToAssignment };
}
