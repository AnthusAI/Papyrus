import { assignmentDoctrine, resolveEditorialContext, type EditorialClient } from "../shared/editorial-context";
import { tenantIdFromEnvironment } from "../../../lib/tenant-keys";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";
import { putJsonModelPayload, readJsonModelPayload, readEditorialAttachment } from "../shared/model-payloads";

type AssignmentHandler =
  | Schema["claimAssignment"]["functionHandler"]
  | Schema["releaseAssignment"]["functionHandler"]
  | Schema["completeAssignment"]["functionHandler"]
  | Schema["cancelAssignment"]["functionHandler"]
  | Schema["reopenAssignment"]["functionHandler"]
  | Schema["retryImmediateAssignment"]["functionHandler"]
  | Schema["getAssignmentContext"]["functionHandler"]
  | Schema["getEditorialContext"]["functionHandler"]
  | Schema["listAssignmentQueue"]["functionHandler"]
  | Schema["listAssignmentsForObject"]["functionHandler"];
type DataClient = ReturnType<typeof generateClient<Schema>>;
type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;
type DataClientResult<T = unknown> = {
  data?: T | null;
  errors?: DataClientErrors;
  nextToken?: string | null;
};

const FINAL_STATUSES = new Set(["completed", "canceled"]);
const IMMEDIATE_ASSIGNMENT_TYPES = new Set(["procedure.run"]);
const NEWSROOM_SUMMARY_PAYLOAD_ID = "knowledge-raw-payload-newsroom-summary-current";
const NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND = "knowledgeRawPayload";
const SUMMARY_STALE_AFTER_MS = 15 * 60 * 1000;
let clientPromise: Promise<DataClient> | null = null;
let editorialEndpoint: string | undefined;

export const handler = async (event: any): Promise<any> => {
  const fieldName = normalizeRequiredString(event.info?.fieldName ?? event.fieldName, "fieldName");
  if (fieldName === "getEditorialContext") return getEditorialContext(event as Parameters<Schema["getEditorialContext"]["functionHandler"]>[0]);
  if (fieldName === "getAssignmentContext") return getAssignmentContext(event as Parameters<Schema["getAssignmentContext"]["functionHandler"]>[0]);
  if (fieldName === "listAssignmentQueue") return listAssignmentQueue(event as Parameters<Schema["listAssignmentQueue"]["functionHandler"]>[0]);
  if (fieldName === "listAssignmentsForObject") return listAssignmentsForObject(event as Parameters<Schema["listAssignmentsForObject"]["functionHandler"]>[0]);
  if (fieldName === "retryImmediateAssignment") return retryImmediateAssignment(event as Parameters<Schema["retryImmediateAssignment"]["functionHandler"]>[0]);
  return mutateAssignment(event as Parameters<Schema["claimAssignment"]["functionHandler"]>[0], fieldName);
};

async function mutateAssignment(event: Parameters<Schema["claimAssignment"]["functionHandler"]>[0], fieldName: string) {
  const client = await getDataClient();
  const assignmentId = normalizeRequiredString(event.arguments.assignmentId, "assignmentId");
  const assignment = await getRequiredRecord(client.models.Assignment, assignmentId, "Assignment");
  const action = assignmentActionFromField(fieldName);
  const now = new Date().toISOString();
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const next = nextAssignmentUpdate(assignment, action, event.arguments, now);
  await requireDataResult(client.models.Assignment.update({ id: assignmentId, ...next }), `update Assignment ${assignmentId}`);
  const eventId = `assignment-event-${assignmentId}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const eventMetadata: Record<string, unknown> = { fieldName };
  if (action === "claim") {
    eventMetadata.assigneeKey = next.assigneeKey ?? null;
    eventMetadata.claimExpiresAt = next.claimExpiresAt ?? null;
    eventMetadata.previousAssigneeKey = normalizeOptionalString(assignment.assigneeKey);
  }
  await requireDataResult(
    client.models.AssignmentEvent.create({
      id: eventId,
      assignmentId,
      assignmentTypeKey: assignment.assignmentTypeKey,
      queueKey: assignment.queueKey,
      eventType: action,
      fromStatus: assignment.status,
      toStatus: next.status ?? assignment.status,
      actorSub,
      actorLabel,
      note: normalizeOptionalString(event.arguments.note),
      createdAt: now,
    }),
    `create AssignmentEvent ${eventId}`,
  );
  await putJsonModelPayload(
    client as any,
    { ownerKind: "assignmentEvent", ownerId: eventId, ownerLineageId: eventId },
    "metadata",
    "metadata",
    eventMetadata,
    { filename: "metadata.json", now },
  );
  await updateNewsroomSummaryForAssignmentAction(client, {
    assignmentTypeKey: normalizeOptionalString(assignment.assignmentTypeKey),
    sectionKey: assignmentSectionKey(assignment),
    previousStatus: normalizeOptionalString(assignment.status),
    nextStatus: normalizeOptionalString(next.status) ?? normalizeOptionalString(assignment.status),
    now,
  });
  let finalStatus = normalizeOptionalString(next.status) ?? normalizeOptionalString(assignment.status) ?? "open";
  if (action === "claim" && assignmentExecutionMode(assignment.assignmentTypeKey) === "immediate") {
    const execution = await executeImmediateClaimedAssignment(client, {
      assignment: { ...assignment, ...next, id: assignmentId },
      actorSub,
      actorLabel,
      now: new Date().toISOString(),
      note: normalizeOptionalString(event.arguments.note),
      trigger: "claim",
    });
    finalStatus = execution.status;
  }
  return {
    ok: true,
    assignmentId,
    eventId,
    status: finalStatus,
    action,
    assigneeKey: normalizeOptionalString(next.assigneeKey),
    claimExpiresAt: normalizeOptionalString(next.claimExpiresAt),
  };
}

async function retryImmediateAssignment(event: Parameters<Schema["retryImmediateAssignment"]["functionHandler"]>[0]) {
  const client = await getDataClient();
  const assignmentId = normalizeRequiredString(event.arguments.assignmentId, "assignmentId");
  const assignment = await getRequiredRecord(client.models.Assignment, assignmentId, "Assignment");
  if (assignmentExecutionMode(assignment.assignmentTypeKey) !== "immediate") {
    throw new Error(`Assignment ${assignmentId} is ${assignment.assignmentTypeKey}; only immediate assignment types support retry.`);
  }
  if (normalizeOptionalString(assignment.status) !== "open") {
    throw new Error(`Assignment ${assignmentId} is ${assignment.status}; retry requires open status.`);
  }
  const actorSub = normalizeOptionalString(event.arguments.actorSub) ?? getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event);
  const now = new Date().toISOString();
  const retryRunId = normalizeOptionalString(assignment.assignmentTypeKey) === "procedure.run"
    ? await cloneProcedureRunForRetry(client, assignment, now, actorLabel ?? actorSub ?? "Papyrus newsroom")
    : null;
  const claimIdentity = resolveClaimIdentity({
    assigneeType: "user",
    assigneeId: actorSub ?? actorLabel ?? "unknown",
    assigneeKey: `user#${actorSub ?? actorLabel ?? "unknown"}`,
  });
  const claimedUpdate = {
    status: "claimed",
    queueStatusKey: `${assignment.queueKey}#claimed`,
    sectionStatusKey: sectionStatusKey(assignment, "claimed"),
    sectionQueueStatusKey: sectionQueueStatusKey(assignment, "claimed"),
    assigneeType: claimIdentity.assigneeType,
    assigneeId: claimIdentity.assigneeId,
    assigneeKey: claimIdentity.assigneeKey,
    claimedAt: now,
    claimExpiresAt: null,
    sourceSnapshotId: retryRunId ?? assignment.sourceSnapshotId ?? null,
    updatedAt: now,
  };
  await requireDataResult(client.models.Assignment.update({ id: assignmentId, ...claimedUpdate }), `retry claim Assignment ${assignmentId}`);
  const retryEventId = `assignment-event-${assignmentId}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  await requireDataResult(
    client.models.AssignmentEvent.create({
      id: retryEventId,
      assignmentId,
      assignmentTypeKey: assignment.assignmentTypeKey,
      queueKey: assignment.queueKey,
      eventType: "retry",
      fromStatus: assignment.status,
      toStatus: "claimed",
      actorSub,
      actorLabel,
      note: normalizeOptionalString(event.arguments.note) ?? "manual immediate retry",
      createdAt: now,
    }),
    `create AssignmentEvent ${retryEventId}`,
  );
  await updateNewsroomSummaryForAssignmentAction(client, {
    assignmentTypeKey: normalizeOptionalString(assignment.assignmentTypeKey),
    sectionKey: assignmentSectionKey(assignment),
    previousStatus: normalizeOptionalString(assignment.status),
    nextStatus: "claimed",
    now,
  });
  const execution = await executeImmediateClaimedAssignment(client, {
    assignment: { ...assignment, ...claimedUpdate, id: assignmentId },
    actorSub,
    actorLabel,
    now: new Date().toISOString(),
    note: normalizeOptionalString(event.arguments.note),
    trigger: "retry",
  });
  return {
    ok: true,
    assignmentId,
    eventId: retryEventId,
    status: execution.status,
    action: "retry",
    assigneeKey: claimIdentity.assigneeKey,
    claimExpiresAt: null,
  };
}

async function cloneProcedureRunForRetry(client: DataClient, assignment: any, now: string, actorLabel: string): Promise<string> {
  const sourceRunId = normalizeOptionalString(assignment.sourceSnapshotId);
  if (!sourceRunId) throw new Error(`Assignment ${assignment.id} has no sourceSnapshotId for immediate retry.`);
  const priorRun = await getRequiredRecord((client.models as any).ProcedureRun, sourceRunId, "ProcedureRun");
  const nextAttempt = (normalizeOptionalPositiveInteger(priorRun.attempt) ?? 1) + 1;
  const retryRunId = `procedure-run-retry-${safeId(assignment.id)}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 6)}`;
  await requireDataResult((client.models as any).ProcedureRun.create({
    id: retryRunId,
    procedureId: priorRun.procedureId,
    procedureKey: priorRun.procedureKey,
    procedureVersionId: priorRun.procedureVersionId,
    procedureVersionNumber: priorRun.procedureVersionNumber ?? null,
    assignmentId: assignment.id,
    runStatus: "queued",
    requestedBy: actorLabel,
    requestedAt: now,
    startedAt: null,
    finishedAt: null,
    input: toAwsJson(priorRun.input ?? {}),
    normalizedInput: toAwsJson(priorRun.normalizedInput ?? priorRun.input ?? {}),
    resultSummary: null,
    errorSummary: null,
    output: null,
    error: null,
    attempt: nextAttempt,
    newsroomFeedKey: priorRun.newsroomFeedKey ?? "procedures",
  }), `create ProcedureRun retry ${retryRunId}`);
  return retryRunId;
}

async function updateNewsroomSummaryForAssignmentAction(
  client: DataClient,
  input: { assignmentTypeKey: string | null; sectionKey: string | null; previousStatus: string | null; nextStatus: string | null; now: string },
): Promise<void> {
  const response = await client.models.KnowledgeRawPayload.get({ id: NEWSROOM_SUMMARY_PAYLOAD_ID });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const payload = normalizeSummaryPayload(await readNewsroomSummaryPayload(client), input.now);
  payload.generatedAt = input.now;
  payload.staleAt = new Date(Date.parse(input.now) + SUMMARY_STALE_AFTER_MS).toISOString();
  payload.source = "incremental";
  payload.counts.assignmentEvents = Math.max(0, (payload.counts.assignmentEvents ?? 0) + 1);
  payload.counts.modelAttachments = Math.max(0, (payload.counts.modelAttachments ?? 0) + 1);
  increment(payload.facets.modelAttachments.byOwnerKind, "assignmentEvent", 1);
  increment(payload.facets.modelAttachments.byRole, "metadata", 1);
  increment(payload.facets.modelAttachments.byMediaType, "application/json", 1);
  increment(payload.facets.modelAttachments.byStatus, "active", 1);
  if (input.previousStatus && input.nextStatus && input.previousStatus !== input.nextStatus) {
    increment(payload.assignmentStatusCounts, input.previousStatus, -1);
    increment(payload.assignmentStatusCounts, input.nextStatus, 1);
    increment(payload.facets.assignments.byStatus, input.previousStatus, -1);
    increment(payload.facets.assignments.byStatus, input.nextStatus, 1);
    if (input.assignmentTypeKey) {
      if (!payload.facets.assignments.statusByType[input.assignmentTypeKey]) payload.facets.assignments.statusByType[input.assignmentTypeKey] = {};
      increment(payload.facets.assignments.statusByType[input.assignmentTypeKey], input.previousStatus, -1);
      increment(payload.facets.assignments.statusByType[input.assignmentTypeKey], input.nextStatus, 1);
    }
    const sectionKey = input.sectionKey || "unsectioned";
    if (!payload.facets.assignments.statusBySection[sectionKey]) payload.facets.assignments.statusBySection[sectionKey] = {};
    increment(payload.facets.assignments.statusBySection[sectionKey], input.previousStatus, -1);
    increment(payload.facets.assignments.statusBySection[sectionKey], input.nextStatus, 1);
  }
  await upsertNewsroomSummaryPayload(client, payload, response.data, input.now);
}

async function getAssignmentContext(event: Parameters<Schema["getAssignmentContext"]["functionHandler"]>[0]) {
  const client = await getDataClient();
  const assignmentId = normalizeRequiredString(event.arguments.assignmentId, "assignmentId");
  const assignment = await getRequiredRecord(client.models.Assignment, assignmentId, "Assignment");
  return buildAssignmentContext(client, assignment);
}

async function listAssignmentQueue(event: Parameters<Schema["listAssignmentQueue"]["functionHandler"]>[0]) {
  const client = await getDataClient();
  const queueKey = normalizeRequiredString(event.arguments.queueKey, "queueKey");
  const status = normalizeOptionalString(event.arguments.status) ?? "open";
  const queueStatusKey = `${queueKey}#${status}`;
  const model = client.models.Assignment as any;
  const assignments: any[] = [];
  let nextToken: string | null | undefined;
  do {
    const response: DataClientResult<any[]> = await model.listAssignmentsByQueueStatusAndPriority(
      { queueStatusKey },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(response.errors, "list Assignment queue");
    assignments.push(...(response.data ?? []));
    nextToken = response.nextToken;
  } while (nextToken);
  assignments.sort((left, right) => assignmentSortKey(left).localeCompare(assignmentSortKey(right)));
  const limit = Math.max(1, Math.min(100, Number(event.arguments.limit ?? 25)));
  const contexts = [];
  for (const assignment of assignments.slice(0, limit)) contexts.push(await buildAssignmentContext(client, assignment));
  return contexts;
}

async function listAssignmentsForObject(event: Parameters<Schema["listAssignmentsForObject"]["functionHandler"]>[0]) {
  const client = await getDataClient();
  const objectKind = normalizeRequiredString(event.arguments.objectKind, "objectKind");
  const objectLineageId = normalizeRequiredString(event.arguments.objectLineageId, "objectLineageId");
  const status = normalizeOptionalString(event.arguments.status);
  const objectStateKey = semanticStateKey(objectKind, objectLineageId);
  const relations = await listRelationPages(client, "listSemanticRelationsByObjectState", { objectStateKey });
  const assignmentIds = Array.from(new Set(relations
    .filter((relation) => relation.relationState === "current" && relation.subjectKind === "assignment")
    .map((relation) => relation.subjectId)
    .filter(Boolean)));
  const assignments = [];
  for (const assignmentId of assignmentIds) {
    const response = await client.models.Assignment.get({ id: assignmentId });
    assertNoDataErrors(response.errors, `get Assignment ${assignmentId}`);
    if (response.data && (!status || response.data.status === status)) assignments.push(response.data);
  }
  assignments.sort((left, right) => assignmentSortKey(left).localeCompare(assignmentSortKey(right)));
  const limit = Math.max(1, Math.min(100, Number(event.arguments.limit ?? 25)));
  const contexts = [];
  for (const assignment of assignments.slice(0, limit)) contexts.push(await buildAssignmentContext(client, assignment));
  return contexts;
}

async function editorialContext(client: DataClient, scope: { publicationKey?: string; sectionId?: string | null; storyLineageId?: string | null; assignmentId?: string | null; maxCharacters?: number | null; optionalPublicationDoctrine?: boolean | null }) {
  if (!editorialEndpoint) throw new Error("Editorial context requires the configured backend endpoint.");
  return resolveEditorialContext(client as unknown as EditorialClient, {
    ...scope, endpoint: editorialEndpoint, tenantId: tenantIdFromEnvironment(), readAttachment: readEditorialAttachment,
  });
}

async function getEditorialContext(event: Parameters<Schema["getEditorialContext"]["functionHandler"]>[0]) {
  const client = await getDataClient();
  return JSON.stringify(await editorialContext(client, {
    ...event.arguments, publicationKey: normalizeRequiredString(event.arguments.publicationKey, "publicationKey"),
  }));
}

async function buildAssignmentContext(client: DataClient, assignment: any) {
  const [relations, events] = await Promise.all([
    listRelationPages(client, "listSemanticRelationsBySubjectState", { subjectStateKey: semanticStateKey("assignment", assignment.id) }),
    listAssignmentEventPages(client, assignment.id),
  ]);
  const targets = relations
    .filter((relation) => relation.relationState === "current")
    .map((relation) => ({
      kind: relation.objectKind,
      id: relation.objectId,
      lineageId: relation.objectLineageId,
      label: targetLabelFromRelation(relation),
      detail: relation.predicate,
    }));
  const pack = await editorialContext(client, { assignmentId: assignment.id });
  const doctrine = assignmentDoctrine(pack);
  return {
    assignment,
    editorialContext: JSON.stringify(pack),
    doctrine,
    targets,
    events,
  };
}


function compactStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => (typeof entry === "string" ? entry.trim() : "")).filter(Boolean);
}

async function listRelationPages(client: DataClient, queryName: string, input: Record<string, unknown>): Promise<any[]> {
  const model = client.models.SemanticRelation as any;
  const query = model[queryName];
  if (typeof query !== "function") throw new Error(`SemanticRelation query ${queryName} is not available.`);
  const records: any[] = [];
  let nextToken: string | null | undefined;
  do {
    const response: DataClientResult<any[]> = await query(input, { limit: 100, nextToken });
    assertNoDataErrors(response.errors, queryName);
    records.push(...(response.data ?? []));
    nextToken = response.nextToken;
  } while (nextToken);
  return records;
}

async function listAssignmentEventPages(client: DataClient, assignmentId: string): Promise<any[]> {
  const model = client.models.AssignmentEvent as any;
  const records: any[] = [];
  let nextToken: string | null | undefined;
  do {
    const response: DataClientResult<any[]> = await model.listAssignmentEventsByAssignmentAndCreatedAt(
      { assignmentId },
      { limit: 100, nextToken },
    );
    assertNoDataErrors(response.errors, "list AssignmentEvent");
    records.push(...(response.data ?? []));
    nextToken = response.nextToken;
  } while (nextToken);
  return records.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
}

function nextAssignmentUpdate(assignment: any, action: string, args: Record<string, unknown>, now: string): Record<string, unknown> {
  if (action === "claim") {
    if (FINAL_STATUSES.has(assignment.status)) throw new Error(`Cannot claim ${assignment.status} assignment ${assignment.id}.`);
    const claimIdentity = resolveClaimIdentity(args);
    if (activeClaimHeldByDifferentAssignee(assignment, claimIdentity.assigneeKey, now)) {
      throw new Error(`Assignment ${assignment.id} is already claimed by ${assignment.assigneeKey}.`);
    }
    const sameAssignee = normalizeOptionalString(assignment.assigneeKey) === claimIdentity.assigneeKey;
    const requestedClaimExpiresAt = resolveClaimExpiresAt(args, now);
    const claimExpiresAt = requestedClaimExpiresAt ?? (sameAssignee ? normalizeOptionalString(assignment.claimExpiresAt) : null);
    return {
      status: "claimed",
      queueStatusKey: `${assignment.queueKey}#claimed`,
      sectionStatusKey: sectionStatusKey(assignment, "claimed"),
      sectionQueueStatusKey: sectionQueueStatusKey(assignment, "claimed"),
      assigneeType: claimIdentity.assigneeType,
      assigneeId: claimIdentity.assigneeId,
      assigneeKey: claimIdentity.assigneeKey,
      claimedAt: sameAssignee && normalizeOptionalString(assignment.claimedAt) ? assignment.claimedAt : now,
      claimExpiresAt,
      updatedAt: now,
    };
  }
  if (action === "release") {
    if (FINAL_STATUSES.has(assignment.status)) throw new Error(`Cannot release ${assignment.status} assignment ${assignment.id}.`);
    return {
      status: "open",
      queueStatusKey: `${assignment.queueKey}#open`,
      sectionStatusKey: sectionStatusKey(assignment, "open"),
      sectionQueueStatusKey: sectionQueueStatusKey(assignment, "open"),
      assigneeType: null,
      assigneeId: null,
      assigneeKey: null,
      claimedAt: null,
      claimExpiresAt: null,
      updatedAt: now,
    };
  }
  if (action === "complete") {
    if (assignment.status === "canceled") throw new Error(`Cannot complete canceled assignment ${assignment.id}.`);
    return {
      status: "completed",
      queueStatusKey: `${assignment.queueKey}#completed`,
      sectionStatusKey: sectionStatusKey(assignment, "completed"),
      sectionQueueStatusKey: sectionQueueStatusKey(assignment, "completed"),
      completedAt: now,
      updatedAt: now,
    };
  }
  if (action === "cancel") {
    if (assignment.status === "completed") throw new Error(`Cannot cancel completed assignment ${assignment.id}.`);
    return {
      status: "canceled",
      queueStatusKey: `${assignment.queueKey}#canceled`,
      sectionStatusKey: sectionStatusKey(assignment, "canceled"),
      sectionQueueStatusKey: sectionQueueStatusKey(assignment, "canceled"),
      canceledAt: now,
      updatedAt: now,
    };
  }
  if (action === "reopen") {
    return {
      status: "open",
      queueStatusKey: `${assignment.queueKey}#open`,
      sectionStatusKey: sectionStatusKey(assignment, "open"),
      sectionQueueStatusKey: sectionQueueStatusKey(assignment, "open"),
      completedAt: null,
      canceledAt: null,
      updatedAt: now,
    };
  }
  throw new Error(`Unsupported assignment action ${action}.`);
}

function assignmentExecutionMode(assignmentTypeKey: unknown): "immediate" | "queued" {
  return IMMEDIATE_ASSIGNMENT_TYPES.has(normalizeOptionalString(assignmentTypeKey) ?? "") ? "immediate" : "queued";
}

async function executeImmediateClaimedAssignment(
  client: DataClient,
  input: {
    assignment: any;
    actorSub: string | null;
    actorLabel: string | null;
    now: string;
    note: string | null;
    trigger: "claim" | "retry";
  },
): Promise<{ status: "completed" | "open"; eventId: string }> {
  const assignmentId = normalizeRequiredString(input.assignment.id, "assignment.id");
  const assignmentTypeKey = normalizeOptionalString(input.assignment.assignmentTypeKey) ?? "unknown";
  const queueKey = normalizeOptionalString(input.assignment.queueKey) ?? `${assignmentTypeKey}#unknown`;
  const startEventId = `assignment-event-${assignmentId}-execution-start-${input.now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 6)}`;
  await requireDataResult(
    client.models.AssignmentEvent.create({
      id: startEventId,
      assignmentId,
      assignmentTypeKey,
      queueKey,
      eventType: "execution_started",
      fromStatus: "claimed",
      toStatus: "claimed",
      actorSub: input.actorSub,
      actorLabel: input.actorLabel,
      note: input.note ?? `${input.trigger} immediate execution`,
      createdAt: input.now,
    }),
    `create AssignmentEvent ${startEventId}`,
  );
  let executionResult: { runId?: string | null; summary: string; output?: unknown } = { summary: "No executor response." };
  try {
    executionResult = await runImmediateAssignmentExecutor(client, input.assignment, input.now);
    const completedAt = new Date().toISOString();
    await requireDataResult(client.models.Assignment.update({
      id: assignmentId,
      status: "completed",
      queueStatusKey: `${queueKey}#completed`,
      sectionStatusKey: sectionStatusKey(input.assignment, "completed"),
      sectionQueueStatusKey: sectionQueueStatusKey(input.assignment, "completed"),
      completedAt,
      updatedAt: completedAt,
    }), `complete immediate Assignment ${assignmentId}`);
    const completeEventId = `assignment-event-${assignmentId}-execution-complete-${completedAt.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 6)}`;
    await requireDataResult(
      client.models.AssignmentEvent.create({
        id: completeEventId,
        assignmentId,
        assignmentTypeKey,
        queueKey,
        eventType: "execution_completed",
        fromStatus: "claimed",
        toStatus: "completed",
        actorSub: input.actorSub,
        actorLabel: input.actorLabel,
        note: executionResult.summary,
        createdAt: completedAt,
      }),
      `create AssignmentEvent ${completeEventId}`,
    );
    await putJsonModelPayload(
      client as any,
      { ownerKind: "assignmentEvent", ownerId: completeEventId, ownerLineageId: completeEventId },
      "result",
      "result",
      {
        trigger: input.trigger,
        runId: executionResult.runId ?? null,
        summary: executionResult.summary,
        output: executionResult.output ?? null,
      },
      { filename: "result.json", now: completedAt },
    );
    await updateNewsroomSummaryForAssignmentAction(client, {
      assignmentTypeKey,
      sectionKey: assignmentSectionKey(input.assignment),
      previousStatus: "claimed",
      nextStatus: "completed",
      now: completedAt,
    });
    return { status: "completed", eventId: completeEventId };
  } catch (error) {
    const failedAt = new Date().toISOString();
    const errorMessage = error instanceof Error ? error.message : "Immediate execution failed.";
    await requireDataResult(client.models.Assignment.update({
      id: assignmentId,
      status: "open",
      queueStatusKey: `${queueKey}#open`,
      sectionStatusKey: sectionStatusKey(input.assignment, "open"),
      sectionQueueStatusKey: sectionQueueStatusKey(input.assignment, "open"),
      assigneeType: null,
      assigneeId: null,
      assigneeKey: null,
      claimedAt: null,
      claimExpiresAt: null,
      updatedAt: failedAt,
    }), `reopen failed immediate Assignment ${assignmentId}`);
    const failedEventId = `assignment-event-${assignmentId}-execution-failed-${failedAt.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 6)}`;
    await requireDataResult(
      client.models.AssignmentEvent.create({
        id: failedEventId,
        assignmentId,
        assignmentTypeKey,
        queueKey,
        eventType: "execution_failed",
        fromStatus: "claimed",
        toStatus: "open",
        actorSub: input.actorSub,
        actorLabel: input.actorLabel,
        note: errorMessage,
        createdAt: failedAt,
      }),
      `create AssignmentEvent ${failedEventId}`,
    );
    await putJsonModelPayload(
      client as any,
      { ownerKind: "assignmentEvent", ownerId: failedEventId, ownerLineageId: failedEventId },
      "error",
      "error",
      {
        trigger: input.trigger,
        runId: executionResult.runId ?? null,
        error: errorMessage,
      },
      { filename: "error.json", now: failedAt },
    );
    await updateNewsroomSummaryForAssignmentAction(client, {
      assignmentTypeKey,
      sectionKey: assignmentSectionKey(input.assignment),
      previousStatus: "claimed",
      nextStatus: "open",
      now: failedAt,
    });
    return { status: "open", eventId: failedEventId };
  }
}

async function runImmediateAssignmentExecutor(client: DataClient, assignment: any, now: string): Promise<{ runId?: string | null; summary: string; output?: unknown }> {
  const assignmentTypeKey = normalizeOptionalString(assignment.assignmentTypeKey) ?? "";
  if (assignmentTypeKey === "procedure.run") {
    return await executeImmediateProcedureRun(client, assignment, now);
  }
  throw new Error(`No immediate executor is registered for ${assignmentTypeKey}.`);
}

async function executeImmediateProcedureRun(client: DataClient, assignment: any, now: string): Promise<{ runId?: string | null; summary: string; output?: unknown }> {
  const runId = normalizeOptionalString(assignment.sourceSnapshotId);
  if (!runId) throw new Error(`Assignment ${assignment.id} is missing sourceSnapshotId for procedure run execution.`);
  const run = await getRequiredRecord((client.models as any).ProcedureRun, runId, "ProcedureRun");
  const version = await getRequiredRecord((client.models as any).ProcedureVersion, normalizeRequiredString(run.procedureVersionId, "procedureVersionId"), "ProcedureVersion");
  const definition = await getRequiredRecord((client.models as any).ProcedureDefinition, normalizeRequiredString(run.procedureId, "procedureId"), "ProcedureDefinition");
  const attempt = normalizeOptionalPositiveInteger(run.attempt) ?? 1;
  const inputPayload = parseJsonObject(run.normalizedInput) ?? parseJsonObject(run.input) ?? {};
  const startedAt = run.startedAt ?? now;
  try {
    const procedureKey = normalizeOptionalString(definition.procedureKey) ?? "unknown";
    const procedureKind = resolveProcedureKind(version, definition);
    const payload = executeSeededProcedurePayload({
      procedureKey,
      procedureKind,
      assignmentId: normalizeOptionalString(assignment.id),
      runId: run.id,
      attempt,
      now,
      input: inputPayload,
    });
    const executionOutput = {
      procedureKey,
      procedureKind,
      versionNumber: Number(version.versionNumber ?? 1),
      attempt,
      executedAt: now,
      mode: "immediate",
      input: inputPayload,
      ...payload,
    };
    const finishedAt = new Date().toISOString();
    await requireDataResult((client.models as any).ProcedureRun.update({
      id: run.id,
      runStatus: "completed",
      startedAt,
      finishedAt,
      resultSummary: `Completed immediate run for ${definition.procedureKey} v${version.versionNumber}.`,
      errorSummary: null,
      output: toAwsJson(executionOutput),
      error: null,
      attempt,
    }), `update ProcedureRun ${run.id}`);
    return {
      runId: run.id,
      summary: `Procedure ${definition.procedureKey} completed.`,
      output: executionOutput,
    };
  } catch (error) {
    const finishedAt = new Date().toISOString();
    const errorMessage = error instanceof Error ? error.message : "Procedure execution failed.";
    await requireDataResult((client.models as any).ProcedureRun.update({
      id: run.id,
      runStatus: "failed",
      startedAt,
      finishedAt,
      resultSummary: null,
      errorSummary: errorMessage,
      output: null,
      error: toAwsJson({
        message: errorMessage,
        procedureKey: normalizeOptionalString(definition.procedureKey),
        procedureVersionId: normalizeOptionalString(version.id),
      }),
      attempt,
    }), `update failed ProcedureRun ${run.id}`);
    throw error;
  }
}

function resolveProcedureKind(version: any, definition: any): string {
  const source = String(version?.tactusSource ?? "");
  const marker = source.match(/papyrus-procedure-kind:\s*([a-z0-9._-]+)/i)?.[1];
  if (marker) return marker;
  return normalizeOptionalString(definition?.procedureKey) ?? "unknown";
}

function executeSeededProcedurePayload(input: {
  procedureKey: string;
  procedureKind: string;
  assignmentId: string | null;
  runId: string;
  attempt: number;
  now: string;
  input: Record<string, unknown>;
}): Record<string, unknown> {
  if (input.procedureKind === "newsroom.research.explorer") {
    return {
      research_packet: buildLambdaResearchPacket(input),
      retry_count: 0,
      validation_failures: [],
    };
  }
  if (input.procedureKind === "newsroom.reporting.context") {
    return {
      reporting_context_packet: buildLambdaReportingPacket(input),
    };
  }
  if (input.procedureKind === "ingestion.reference.register") {
    const registerResult = runIngestionReferenceRegisterViaCli(input);
    return {
      result: {
        ok: true,
        kind: "ingestion.reference.register",
        assignmentId: input.assignmentId,
        runId: input.runId,
        register: registerResult,
      },
    };
  }
  throw new Error(`Unsupported seeded procedure kind '${input.procedureKind}' for ${input.procedureKey}.`);
}

function runIngestionReferenceRegisterViaCli(input: {
  procedureKind: string;
  input: Record<string, unknown>;
}): Record<string, unknown> {
  const externalItemId = normalizeRequiredString(
    input.input.externalItemId ?? input.input.external_item_id,
    "input.externalItemId",
  );
  const sourceUri = normalizeRequiredString(
    input.input.sourceUri ?? input.input.source_uri,
    "input.sourceUri",
  );
  const title = normalizeOptionalString(input.input.title) ?? "Untitled source";
  const corpusKey = normalizeOptionalString(input.input.corpusKey ?? input.input.corpus_key) ?? "AI-ML-research";
  const ingestionRationale = normalizeOptionalString(input.input.ingestionRationale ?? input.input.ingestion_rationale)
    ?? `Registered from procedure ingestion.reference.register for ${externalItemId}.`;
  const tempDir = mkdtempSync(path.join(tmpdir(), "papyrus-ingestion-reference-register-"));
  const catalogPath = path.join(tempDir, "catalog.json");
  writeFileSync(
    catalogPath,
    JSON.stringify({
      schema_version: 1,
      items: [
        {
          id: externalItemId,
          item_id: externalItemId,
          external_item_id: externalItemId,
          title,
          source_uri: sourceUri,
          ingestion_rationale: ingestionRationale,
        },
      ],
    }, null, 2),
    "utf8",
  );
  try {
    const register = spawnSync(
      "npm",
      [
        "run",
        "content",
        "--",
        "references",
        "register-catalog",
        "--catalog",
        catalogPath,
        "--corpus-key",
        corpusKey,
        "--status",
        "pending",
        "--vector-sync",
        "false",
        "--url-text",
        "false",
        "--metadata-from-text",
        "false",
        "--apply",
      ],
      { encoding: "utf8" },
    );
    if (register.status !== 0) {
      throw new Error((register.stderr || register.stdout || "register-catalog failed").trim());
    }
    const fetch = spawnSync(
      "npm",
      [
        "run",
        "content",
        "--",
        "references",
        "fetch-url-text",
        "--corpus-key",
        corpusKey,
        "--external-item-id",
        externalItemId,
        "--status",
        "all",
        "--max-count",
        "1",
        "--apply",
      ],
      { encoding: "utf8" },
    );
    if (fetch.status !== 0) {
      throw new Error((fetch.stderr || fetch.stdout || "fetch-url-text failed").trim());
    }
    const generate = spawnSync(
      "npm",
      [
        "run",
        "content",
        "--",
        "references",
        "generate-metadata-from-text",
        "--corpus-key",
        corpusKey,
        "--external-item-id",
        externalItemId,
        "--status",
        "all",
        "--model",
        "gpt-5.4-nano",
        "--max-count",
        "1",
        "--apply",
      ],
      { encoding: "utf8" },
    );
    if (generate.status !== 0) {
      throw new Error((generate.stderr || generate.stdout || "generate-metadata-from-text failed").trim());
    }
    return {
      externalItemId,
      sourceUri,
      corpusKey,
      registerExitCode: register.status ?? 0,
      fetchExitCode: fetch.status ?? 0,
      generateExitCode: generate.status ?? 0,
      fetchedTextChanges: parseTsvMetric(fetch.stdout, "references", "fetch-url-text", "changes"),
      fetchedTextFailures: parseTsvMetric(fetch.stdout, "references", "fetch-url-text", "failures"),
      metadataAttempted: parseTsvMetric(generate.stdout, "references", "generate-metadata-from-text", "attempted"),
      metadataGenerated: parseTsvMetric(generate.stdout, "references", "generate-metadata-from-text", "generated"),
      metadataSkippedMissingText: parseTsvMetric(generate.stdout, "references", "generate-metadata-from-text", "skipped-missing-text"),
      metadataGenerationFailures: parseTsvMetric(generate.stdout, "references", "generate-metadata-from-text", "generation-failures"),
    };
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function parseTsvMetric(output: string, section: string, command: string, field: string): number | null {
  const lines = (output || "").split(/\r?\n/);
  for (const line of lines) {
    const parts = line.trim().split("\t");
    if (parts.length < 4) continue;
    if (parts[0] === section && parts[1] === command && parts[2] === field) {
      const value = Number(parts[3]);
      return Number.isFinite(value) ? value : null;
    }
  }
  return null;
}

function buildLambdaResearchPacket(input: {
  procedureKey: string;
  assignmentId: string | null;
  runId: string;
  now: string;
  input: Record<string, unknown>;
}): Record<string, unknown> {
  const researchMode = normalizeOptionalString(input.input.research_mode) ?? "source_discovery";
  const corpusKey = normalizeOptionalString(input.input.corpus_key);
  const question = normalizeOptionalString(input.input.research_questions);
  const blockedReason = "Lambda immediate seeded procedure executed without external Tactus tool calls.";
  return {
    summary: `Immediate research packet generated for ${input.assignmentId ?? "assignment"}.`,
    corpus_key: corpusKey,
    research_mode: researchMode,
    queries: question ? [question] : [],
    evidence_item_ids: [],
    source_snapshots: [],
    proposed_references: [],
    source_discovery: {
      source_snapshots: [],
      proposed_references: [],
      blocked_reason: blockedReason,
    },
    recommended_angle: "Gather accepted references before drafting reporting context.",
    open_questions: [
      "Which accepted references should anchor this angle?",
    ],
    coverage_gaps: [
      "No external discovery executed in immediate Lambda seeded procedure mode.",
    ],
    researchTrace: {
      recoveryPath: "lambda_immediate_seeded_procedure",
      runId: input.runId,
      executedAt: input.now,
      blockedReason,
    },
  };
}

function buildLambdaReportingPacket(input: {
  assignmentId: string | null;
  runId: string;
  now: string;
  input: Record<string, unknown>;
}): Record<string, unknown> {
  return {
    editor_recommendation: "hold",
    recommended_angle: "Collect stronger accepted-reference evidence before copywriting.",
    accepted_reference_ids: [],
    risk_flags: [
      "Immediate seeded Lambda procedure produced a placeholder reporting packet.",
    ],
    coverage_gaps: [
      "Run full reporting procedure after confirming source research packet and accepted references.",
    ],
    open_questions: [
      "What primary claim should this section make next?",
    ],
    copywriter_brief: "Hold draft creation until reporting packet evidence is enriched.",
    source_research_assignment_id: normalizeOptionalString(input.input.source_research_assignment_id),
    source_research_packet_id: normalizeOptionalString(input.input.source_research_packet_id),
    source_research_packet_path: normalizeOptionalString(input.input.source_research_packet_path),
    run_id: input.runId,
    generated_at: input.now,
    assignment_id: input.assignmentId,
  };
}

function assignmentSectionKey(assignment: any): string | null {
  return normalizeOptionalString(assignment?.sectionKey)
    ?? normalizeOptionalString(assignment?.sectionId);
}

function sectionStatusKey(assignment: any, status: string): string | null {
  const sectionKey = assignmentSectionKey(assignment);
  return sectionKey ? `${sectionKey}#${status}` : null;
}

function sectionQueueStatusKey(assignment: any, status: string): string | null {
  const sectionKey = assignmentSectionKey(assignment);
  const queueKey = normalizeOptionalString(assignment?.queueKey);
  return sectionKey && queueKey ? `${sectionKey}#${queueKey}#${status}` : null;
}

function resolveClaimIdentity(args: Record<string, unknown>): { assigneeType: string | null; assigneeId: string | null; assigneeKey: string } {
  const explicitAssigneeKey = normalizeOptionalString(args.assigneeKey);
  if (explicitAssigneeKey) {
    return {
      assigneeType: normalizeOptionalString(args.assigneeType),
      assigneeId: normalizeOptionalString(args.assigneeId),
      assigneeKey: explicitAssigneeKey,
    };
  }
  const assigneeType = normalizeOptionalString(args.assigneeType) ?? "user";
  const assigneeId = normalizeOptionalString(args.assigneeId) ?? normalizeOptionalString(args.actorSub) ?? "unknown";
  return {
    assigneeType,
    assigneeId,
    assigneeKey: `${assigneeType}#${assigneeId}`,
  };
}

function activeClaimHeldByDifferentAssignee(assignment: any, requestedAssigneeKey: string, now: string): boolean {
  if (assignment.status !== "claimed") return false;
  const currentAssigneeKey = normalizeOptionalString(assignment.assigneeKey);
  if (!currentAssigneeKey || currentAssigneeKey === requestedAssigneeKey) return false;
  const claimExpiresAt = normalizeOptionalString(assignment.claimExpiresAt);
  if (!claimExpiresAt) return true;
  const expirationTime = Date.parse(claimExpiresAt);
  if (!Number.isFinite(expirationTime)) return true;
  return expirationTime > Date.parse(now);
}

function resolveClaimExpiresAt(args: Record<string, unknown>, now: string): string | null {
  const explicitExpiration = normalizeOptionalString(args.claimExpiresAt);
  if (explicitExpiration) {
    const expirationTime = Date.parse(explicitExpiration);
    if (!Number.isFinite(expirationTime)) throw new Error(`Invalid claimExpiresAt value ${explicitExpiration}.`);
    return new Date(expirationTime).toISOString();
  }
  const ttlSeconds = normalizeOptionalPositiveInteger(args.claimTtlSeconds);
  if (!ttlSeconds) return null;
  return new Date(Date.parse(now) + ttlSeconds * 1000).toISOString();
}

function normalizeOptionalPositiveInteger(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) throw new Error(`Expected a positive integer, got ${String(value)}.`);
  return parsed;
}

function assignmentActionFromField(fieldName: string): string {
  if (fieldName === "claimAssignment") return "claim";
  if (fieldName === "releaseAssignment") return "release";
  if (fieldName === "completeAssignment") return "complete";
  if (fieldName === "cancelAssignment") return "cancel";
  if (fieldName === "reopenAssignment") return "reopen";
  throw new Error(`Unsupported assignment action ${fieldName}.`);
}

async function getDataClient(): Promise<DataClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const { resourceConfig, libraryOptions } = await getAmplifyDataClientConfig(process.env as never);
      Amplify.configure(resourceConfig, libraryOptions);
      editorialEndpoint = resourceConfig.API?.GraphQL?.endpoint;
      return generateClient<Schema>();
    })();
  }
  return clientPromise;
}

async function getRequiredRecord(
  model: { get(input: { id: string }): Promise<{ data?: unknown | null; errors?: DataClientErrors }> },
  id: string,
  modelName: string,
): Promise<any> {
  const response = await model.get({ id });
  assertNoDataErrors(response.errors, `get ${modelName}`);
  if (!response.data) throw new Error(`${modelName} ${id} was not found.`);
  return response.data;
}

async function requireDataResult<T>(promise: Promise<DataClientResult<T>>, operation: string): Promise<T> {
  const response = await promise;
  assertNoDataErrors(response.errors, operation);
  if (!response.data) throw new Error(`${operation} returned no data.`);
  return response.data;
}

function assertNoDataErrors(errors: DataClientErrors, operation: string): void {
  if (!errors?.length) return;
  throw new Error(`${operation} failed: ${errors.map(formatDataError).join("; ")}`);
}

function formatDataError(error: { message?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  return error?.message ?? "GraphQL data operation failed.";
}

function semanticStateKey(kind: string, lineageId: string): string {
  return `${kind}#${lineageId}#current`;
}

function assignmentSortKey(assignment: any): string {
  return `${String(assignment.priority ?? 999999).padStart(6, "0")}#${assignment.createdAt ?? ""}#${assignment.id}`;
}

function targetLabelFromRelation(relation: any): string {
  const metadata = parseJsonObject(relation.metadata);
  return normalizeOptionalString(metadata?.title)
    ?? normalizeOptionalString(metadata?.displayName)
    ?? normalizeOptionalString(metadata?.externalItemId)
    ?? relation.objectLineageId;
}

function parseJsonObject(value: unknown): Record<string, unknown> | null {
  if (!value) return null;
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function safeId(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    || "item";
}

function normalizeSummaryPayload(value: unknown, now: string): {
  generatedAt: string;
  staleAt: string;
  source: string;
  latestImportRun: Record<string, unknown> | null;
  counts: Record<string, number>;
  assignmentStatusCounts: Record<string, number>;
  assignmentTypeCounts: Record<string, number>;
  referenceStatusCounts: Record<string, number>;
  messageKindCounts: Record<string, number>;
  messageDomainCounts: Record<string, number>;
  facets: {
    assignments: {
      byStatus: Record<string, number>;
      byType: Record<string, number>;
      bySection: Record<string, number>;
      statusByType: Record<string, Record<string, number>>;
      statusBySection: Record<string, Record<string, number>>;
      typeBySection: Record<string, Record<string, number>>;
    };
    messages: { byKind: Record<string, number>; byDomain: Record<string, number>; byStatus: Record<string, number>; domainByKind: Record<string, Record<string, number>> };
    modelAttachments: { byOwnerKind: Record<string, number>; byRole: Record<string, number>; byMediaType: Record<string, number>; byStatus: Record<string, number> };
    references: { byCurationStatus: Record<string, number>; byCorpus: Record<string, number>; statusByCorpus: Record<string, Record<string, number>> };
    semanticNodes: { byNodeKind: Record<string, number>; byStatus: Record<string, number>; byCorpus: Record<string, number>; byCategorySet: Record<string, number> };
    semanticRelations: { byRelationTypeKey: Record<string, number>; byRelationDomain: Record<string, number>; bySubjectKind: Record<string, number>; byObjectKind: Record<string, number> };
    imports: { byCorpus: Record<string, number> };
  };
} {
  const parsed = parseJsonObject(value) ?? {};
  const facets = normalizeFacets(parsed);
  return {
    generatedAt: normalizeOptionalString(parsed.generatedAt) ?? now,
    staleAt: normalizeOptionalString(parsed.staleAt) ?? now,
    source: normalizeOptionalString(parsed.source) ?? "missing",
    latestImportRun: parseJsonObject(parsed.latestImportRun),
    counts: numberRecord(parsed.counts),
    assignmentStatusCounts: numberRecord(parsed.assignmentStatusCounts),
    assignmentTypeCounts: numberRecord(parsed.assignmentTypeCounts),
    referenceStatusCounts: numberRecord(parsed.referenceStatusCounts),
    messageKindCounts: numberRecord(parsed.messageKindCounts),
    messageDomainCounts: numberRecord(parsed.messageDomainCounts),
    facets,
  };
}

function normalizeFacets(payload: Record<string, unknown>): ReturnType<typeof createEmptyFacets> {
  const facets = createEmptyFacets();
  const parsed = parseJsonObject(payload.facets) ?? {};
  const assignments = parseJsonObject(parsed.assignments) ?? {};
  const messages = parseJsonObject(parsed.messages) ?? {};
  const modelAttachments = parseJsonObject(parsed.modelAttachments) ?? {};
  const references = parseJsonObject(parsed.references) ?? {};
  const semanticNodes = parseJsonObject(parsed.semanticNodes) ?? {};
  const semanticRelations = parseJsonObject(parsed.semanticRelations) ?? {};
  const imports = parseJsonObject(parsed.imports) ?? {};
  facets.assignments.byStatus = { ...numberRecord(payload.assignmentStatusCounts), ...numberRecord(assignments.byStatus) };
  facets.assignments.byType = { ...numberRecord(payload.assignmentTypeCounts), ...numberRecord(assignments.byType) };
  facets.assignments.bySection = numberRecord(assignments.bySection);
  facets.assignments.statusByType = nestedNumberRecord(assignments.statusByType);
  facets.assignments.statusBySection = nestedNumberRecord(assignments.statusBySection);
  facets.assignments.typeBySection = nestedNumberRecord(assignments.typeBySection);
  facets.messages.byKind = { ...numberRecord(payload.messageKindCounts), ...numberRecord(messages.byKind) };
  facets.messages.byDomain = { ...numberRecord(payload.messageDomainCounts), ...numberRecord(messages.byDomain) };
  facets.messages.byStatus = numberRecord(messages.byStatus);
  facets.messages.domainByKind = nestedNumberRecord(messages.domainByKind);
  facets.modelAttachments.byOwnerKind = numberRecord(modelAttachments.byOwnerKind);
  facets.modelAttachments.byRole = numberRecord(modelAttachments.byRole);
  facets.modelAttachments.byMediaType = numberRecord(modelAttachments.byMediaType);
  facets.modelAttachments.byStatus = numberRecord(modelAttachments.byStatus);
  facets.references.byCurationStatus = { ...numberRecord(payload.referenceStatusCounts), ...numberRecord(references.byCurationStatus) };
  facets.references.byCorpus = numberRecord(references.byCorpus);
  facets.references.statusByCorpus = nestedNumberRecord(references.statusByCorpus);
  facets.semanticNodes.byNodeKind = numberRecord(semanticNodes.byNodeKind);
  facets.semanticNodes.byStatus = numberRecord(semanticNodes.byStatus);
  facets.semanticNodes.byCorpus = numberRecord(semanticNodes.byCorpus);
  facets.semanticNodes.byCategorySet = numberRecord(semanticNodes.byCategorySet);
  facets.semanticRelations.byRelationTypeKey = numberRecord(semanticRelations.byRelationTypeKey);
  facets.semanticRelations.byRelationDomain = numberRecord(semanticRelations.byRelationDomain);
  facets.semanticRelations.bySubjectKind = numberRecord(semanticRelations.bySubjectKind);
  facets.semanticRelations.byObjectKind = numberRecord(semanticRelations.byObjectKind);
  facets.imports.byCorpus = numberRecord(imports.byCorpus);
  return facets;
}

function createEmptyFacets() {
  return {
    assignments: { byStatus: {}, byType: {}, bySection: {}, statusByType: {}, statusBySection: {}, typeBySection: {} },
    messages: { byKind: {}, byDomain: {}, byStatus: {}, domainByKind: {} },
    modelAttachments: { byOwnerKind: {}, byRole: {}, byMediaType: {}, byStatus: {} },
    references: { byCurationStatus: {}, byCorpus: {}, statusByCorpus: {} },
    semanticNodes: { byNodeKind: {}, byStatus: {}, byCorpus: {}, byCategorySet: {} },
    semanticRelations: { byRelationTypeKey: {}, byRelationDomain: {}, bySubjectKind: {}, byObjectKind: {} },
    imports: { byCorpus: {} },
  };
}

function nestedNumberRecord(value: unknown): Record<string, Record<string, number>> {
  const parsed = parseJsonObject(value) ?? {};
  const result: Record<string, Record<string, number>> = {};
  for (const [key, entry] of Object.entries(parsed)) result[key] = numberRecord(entry);
  return result;
}

async function upsertNewsroomSummaryPayload(
  client: DataClient,
  payload: Record<string, unknown>,
  current: any,
  now: string,
): Promise<void> {
  const input = {
    id: NEWSROOM_SUMMARY_PAYLOAD_ID,
    ownerType: "newsroom",
    ownerId: "newsroom",
    payloadKind: "summary-snapshot",
    importRunId: normalizeOptionalString(parseJsonObject(payload.latestImportRun)?.id),
    createdAt: current?.createdAt ?? now,
    updatedAt: now,
  };
  if (current) {
    await requireDataResult(client.models.KnowledgeRawPayload.update(input), "update Newsroom summary snapshot");
  } else {
    await requireDataResult(client.models.KnowledgeRawPayload.create(input), "create Newsroom summary snapshot");
  }
  await putJsonModelPayload(
    client as any,
    { ownerKind: NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND, ownerId: NEWSROOM_SUMMARY_PAYLOAD_ID, importRunId: input.importRunId },
    "raw_payload",
    "summary-snapshot",
    payload,
    { filename: "summary-snapshot.json", now },
  );
}

async function readNewsroomSummaryPayload(client: DataClient): Promise<Record<string, unknown> | null> {
  return readJsonModelPayload(
    client as any,
    NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND,
    NEWSROOM_SUMMARY_PAYLOAD_ID,
    "raw_payload",
    "summary-snapshot",
  );
}

function numberRecord(value: unknown): Record<string, number> {
  const parsed = parseJsonObject(value) ?? {};
  const result: Record<string, number> = {};
  for (const [key, entry] of Object.entries(parsed)) {
    const numeric = Number(entry);
    if (Number.isFinite(numeric)) result[key] = numeric;
  }
  return result;
}

function increment(target: Record<string, number>, key: string, delta: number): void {
  target[key] = Math.max(0, (target[key] ?? 0) + delta);
}

function normalizeRequiredString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || value.trim().length === 0) throw new Error(`${fieldName} is required.`);
  return value.trim();
}

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function getIdentitySub(event: any): string | null {
  const identity = event.identity as { sub?: string | null; claims?: Record<string, unknown> } | null | undefined;
  return normalizeOptionalString(identity?.sub) ?? normalizeOptionalString(identity?.claims?.sub);
}

function getIdentityLabel(event: any): string | null {
  const identity = event.identity as { username?: string | null; claims?: Record<string, unknown> } | null | undefined;
  return normalizeOptionalString(identity?.claims?.email)
    ?? normalizeOptionalString(identity?.claims?.name)
    ?? normalizeOptionalString(identity?.username)
    ?? getIdentitySub(event);
}

function toAwsJson(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
