import { randomUUID, createHash } from "node:crypto";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";
import { claimGroups } from "../../../lib/staff-groups";

type DataClient = ReturnType<typeof generateClient<Schema>>;
type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;
type DataClientResult<T = unknown> = {
  data?: T | null;
  errors?: DataClientErrors;
  nextToken?: string | null;
};

type ProcedureEvent = {
  arguments: Record<string, unknown>;
  fieldName?: string | null;
  info?: { fieldName?: string | null } | null;
  identity?: { sub?: string | null; username?: string | null; claims?: Record<string, unknown> } | null;
};

const LAMBDA_DATA_AUTH_MODE = "iam";
const IMMEDIATE_ASSIGNMENT_TYPES = new Set(["procedure.run"]);
let clientPromise: Promise<DataClient> | null = null;

export const handler = async (event: ProcedureEvent) => {
  const fieldName = normalizeRequiredString(event.info?.fieldName ?? event.fieldName, "fieldName");
  if (fieldName === "listNewsroomProcedureDefinitions") return listProcedureDefinitions();
  if (fieldName === "getNewsroomProcedureDefinition") return getProcedureDefinition(event.arguments);
  if (fieldName === "saveNewsroomProcedureDefinition") return saveProcedureDefinition(event);
  if (fieldName === "saveNewsroomProcedureVersionDraft") return saveProcedureVersionDraft(event);
  if (fieldName === "publishNewsroomProcedureVersion") return publishProcedureVersion(event);
  if (fieldName === "startNewsroomProcedureRun") return startProcedureRun(event);
  if (fieldName === "getNewsroomProcedureRun") return getProcedureRun(event.arguments);
  if (fieldName === "listNewsroomProcedureRunsByProcedure") return listProcedureRunsByProcedure(event.arguments);
  throw new Error(`Unsupported procedure operation ${fieldName}.`);
};

async function listProcedureDefinitions() {
  const client = await getDataClient();
  const definitions = await listProcedureDefinitionsPage(client);
  const versions = await listProcedureVersionsPage(client);
  const runs = await listProcedureRunsPage(client);
  const versionsByProcedureId = groupBy(versions, (entry) => normalizeOptionalString(entry.procedureId) ?? "");
  const runsByProcedureId = groupBy(runs, (entry) => normalizeOptionalString(entry.procedureId) ?? "");
  return {
    items: definitions.map((definition) => {
      const currentVersion = normalizeOptionalString(definition.currentVersionId)
        ? versions.find((entry) => entry.id === definition.currentVersionId) ?? null
        : null;
      const recentRuns = (runsByProcedureId.get(definition.id) ?? [])
        .sort((left, right) => String(right.requestedAt ?? "").localeCompare(String(left.requestedAt ?? "")))
        .slice(0, 10);
      return {
        ...definition,
        currentVersion,
        recentRuns,
        versions: (versionsByProcedureId.get(definition.id) ?? [])
          .sort((left, right) => (right.versionNumber ?? 0) - (left.versionNumber ?? 0)),
      };
    }),
  };
}

async function getProcedureDefinition(args: Record<string, unknown>) {
  const client = await getDataClient();
  const id = normalizeOptionalString(args.id);
  const procedureKey = normalizeOptionalString(args.procedureKey);
  const definition = id
    ? await getRequiredRecord(client.models.ProcedureDefinition, id, "ProcedureDefinition")
    : await getProcedureDefinitionByKey(client, procedureKey);
  if (!definition) throw new Error("ProcedureDefinition not found.");
  const versions = await listProcedureVersionsByProcedure(client, definition.id);
  const currentVersion = normalizeOptionalString(definition.currentVersionId)
    ? versions.find((entry) => entry.id === definition.currentVersionId) ?? null
    : null;
  return {
    ...definition,
    currentVersion: currentVersion
      ? {
        id: currentVersion.id,
        procedureId: currentVersion.procedureId,
        procedureKey: currentVersion.procedureKey,
        versionNumber: currentVersion.versionNumber,
        status: currentVersion.status,
        isCurrent: currentVersion.isCurrent,
        label: currentVersion.label,
        tactusSource: currentVersion.tactusSource,
        parameterSchema: currentVersion.parameterSchema,
        defaults: currentVersion.defaults,
        changelog: currentVersion.changelog,
        createdBy: currentVersion.createdBy,
        createdAt: currentVersion.createdAt,
        updatedBy: currentVersion.updatedBy,
        updatedAt: currentVersion.updatedAt,
      }
      : null,
    versions: [],
    recentRuns: [],
  };
}

async function saveProcedureDefinition(event: ProcedureEvent) {
  requireAdmin(event);
  const client = await getDataClient();
  const now = new Date().toISOString();
  const actor = getIdentityLabel(event) ?? "Papyrus admin";
  const input = objectValue(event.arguments.input);
  const id = normalizeOptionalString(input.id);
  const procedureKey = normalizeRequiredString(input.procedureKey, "input.procedureKey");
  const recordId = id ?? `procedure-definition-${safeId(procedureKey)}`;
  const existing = await (async () => {
    if (id) return await getOptionalRecord(client.models.ProcedureDefinition, id, "ProcedureDefinition");
    return await getProcedureDefinitionByKey(client, procedureKey);
  })();
  const payload = {
    id: existing?.id ?? recordId,
    procedureKey,
    title: normalizeRequiredString(input.title, "input.title"),
    category: normalizeOptionalString(input.category) ?? "ingestion",
    description: normalizeOptionalString(input.description),
    enabled: normalizeOptionalBoolean(input.enabled, true),
    enabledStatus: normalizeOptionalBoolean(input.enabled, true) ? "enabled" : "disabled",
    currentVersionId: normalizeOptionalString(input.currentVersionId) ?? normalizeOptionalString(existing?.currentVersionId),
    createdBy: normalizeOptionalString(existing?.createdBy) ?? actor,
    createdAt: normalizeOptionalString(existing?.createdAt) ?? now,
    updatedBy: actor,
    updatedAt: now,
    newsroomFeedKey: "procedures",
  };
  const response = existing
    ? await client.models.ProcedureDefinition.update(payload as never, { authMode: LAMBDA_DATA_AUTH_MODE })
    : await client.models.ProcedureDefinition.create(payload as never, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(response.errors, "save ProcedureDefinition");
  if (!response.data) throw new Error("ProcedureDefinition save returned no data.");
  return { ok: true, definition: response.data };
}

async function saveProcedureVersionDraft(event: ProcedureEvent) {
  requireAdmin(event);
  const client = await getDataClient();
  const now = new Date().toISOString();
  const actor = getIdentityLabel(event) ?? "Papyrus admin";
  const input = objectValue(event.arguments.input);
  const versionId = normalizeOptionalString(input.id);
  const definition = await resolveDefinition(client, input);
  if (!definition) throw new Error("ProcedureDefinition not found.");
  const versions = await listProcedureVersionsByProcedure(client, definition.id);
  if (versionId) {
    const existing = await getRequiredRecord(client.models.ProcedureVersion, versionId, "ProcedureVersion");
    if (existing.procedureId !== definition.id) throw new Error(`ProcedureVersion ${versionId} does not belong to ${definition.id}.`);
    if (normalizeOptionalString(existing.status) === "published") throw new Error("Published versions are immutable; create a new draft.");
    const response = await client.models.ProcedureVersion.update({
      id: existing.id,
      label: normalizeOptionalString(input.label) ?? existing.label ?? null,
      tactusSource: normalizeRequiredString(input.tactusSource, "input.tactusSource"),
      parameterSchema: normalizeJson(input.parameterSchema),
      defaults: normalizeOptionalJson(input.defaults),
      changelog: normalizeOptionalString(input.changelog) ?? existing.changelog ?? null,
      updatedBy: actor,
      updatedAt: now,
    } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
    assertNoDataErrors(response.errors, "update ProcedureVersion");
    if (!response.data) throw new Error("ProcedureVersion update returned no data.");
    return { ok: true, version: response.data };
  }
  const nextVersionNumber = Math.max(0, ...versions.map((entry) => Number(entry.versionNumber ?? 0))) + 1;
  const created = await client.models.ProcedureVersion.create({
    id: `procedure-version-${safeId(definition.procedureKey)}-${nextVersionNumber}`,
    procedureId: definition.id,
    procedureKey: definition.procedureKey,
    versionNumber: nextVersionNumber,
    status: "draft",
    isCurrent: false,
    label: normalizeOptionalString(input.label) ?? null,
    tactusSource: normalizeRequiredString(input.tactusSource, "input.tactusSource"),
    parameterSchema: normalizeJson(input.parameterSchema),
    defaults: normalizeOptionalJson(input.defaults),
    changelog: normalizeOptionalString(input.changelog) ?? null,
    createdBy: actor,
    createdAt: now,
    updatedBy: actor,
    updatedAt: now,
  } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(created.errors, "create ProcedureVersion");
  if (!created.data) throw new Error("ProcedureVersion create returned no data.");
  return { ok: true, version: created.data };
}

async function publishProcedureVersion(event: ProcedureEvent) {
  requireAdmin(event);
  const client = await getDataClient();
  const now = new Date().toISOString();
  const actor = getIdentityLabel(event) ?? "Papyrus admin";
  const versionId = normalizeRequiredString(event.arguments.versionId, "versionId");
  const version = await getRequiredRecord(client.models.ProcedureVersion, versionId, "ProcedureVersion");
  const definition = await getRequiredRecord(client.models.ProcedureDefinition, version.procedureId, "ProcedureDefinition");
  const versions = await listProcedureVersionsByProcedure(client, definition.id);
  for (const entry of versions) {
    const isTarget = entry.id === version.id;
    const response = await client.models.ProcedureVersion.update({
      id: entry.id,
      isCurrent: isTarget,
      status: isTarget ? "published" : (normalizeOptionalString(entry.status) === "published" ? "archived" : normalizeOptionalString(entry.status) ?? "draft"),
      updatedBy: actor,
      updatedAt: now,
    } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
    assertNoDataErrors(response.errors, `publish ProcedureVersion ${entry.id}`);
  }
  const definitionResponse = await client.models.ProcedureDefinition.update({
    id: definition.id,
    currentVersionId: version.id,
    enabled: normalizeOptionalBoolean(definition.enabled, true),
    enabledStatus: normalizeOptionalBoolean(definition.enabled, true) ? "enabled" : "disabled",
    updatedBy: actor,
    updatedAt: now,
  } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(definitionResponse.errors, "update ProcedureDefinition currentVersionId");
  return { ok: true, procedureId: definition.id, versionId: version.id };
}

async function startProcedureRun(event: ProcedureEvent) {
  const client = await getDataClient();
  const now = new Date().toISOString();
  const actorSub = getIdentitySub(event);
  const actorLabel = normalizeOptionalString(event.arguments.actorLabel) ?? getIdentityLabel(event) ?? actorSub ?? "Papyrus newsroom";
  const procedureKey = normalizeOptionalString(event.arguments.procedureKey);
  const procedureId = normalizeOptionalString(event.arguments.procedureId);
  const definition = procedureId
    ? await getRequiredRecord(client.models.ProcedureDefinition, procedureId, "ProcedureDefinition")
    : await getProcedureDefinitionByKey(client, procedureKey);
  if (!definition) throw new Error(`Procedure ${procedureKey ?? procedureId ?? "unknown"} was not found.`);
  if (!normalizeOptionalBoolean(definition.enabled, true)) {
    throw new Error(`Procedure ${definition.procedureKey} is disabled.`);
  }
  const versionId = normalizeOptionalString(event.arguments.procedureVersionId) ?? normalizeOptionalString(definition.currentVersionId);
  if (!versionId) throw new Error(`Procedure ${definition.procedureKey} does not have a current version.`);
  const version = await getRequiredRecord(client.models.ProcedureVersion, versionId, "ProcedureVersion");
  const input = normalizeJson(event.arguments.input);
  const executionMode = normalizeOptionalString(input.__papyrusExecutionMode);
  delete input.__papyrusExecutionMode;
  const validation = validateJsonSchemaInput(normalizeJson(version.parameterSchema), input);
  if (!validation.ok) throw new Error(`Procedure parameter validation failed: ${validation.error}`);
  const normalizedInput = validation.normalizedInput;
  const isExternalCliRun = executionMode === "external_cli";
  const runId = `procedure-run-${safeId(definition.procedureKey)}-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
  const assignmentId = isExternalCliRun ? null : `assignment-procedure-run-${hashShort([runId, definition.id, version.id])}`;
  const runResponse = await client.models.ProcedureRun.create({
    id: runId,
    procedureId: definition.id,
    procedureKey: definition.procedureKey,
    procedureVersionId: version.id,
    procedureVersionNumber: Number(version.versionNumber ?? 1),
    assignmentId,
    runStatus: isExternalCliRun ? "running" : "queued",
    requestedBy: actorLabel,
    requestedAt: now,
    startedAt: isExternalCliRun ? now : null,
    finishedAt: null,
    input: toAwsJson(input),
    normalizedInput: toAwsJson(normalizedInput),
    resultSummary: null,
    errorSummary: null,
    output: null,
    error: null,
    attempt: 1,
    newsroomFeedKey: "procedures",
  } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(runResponse.errors, "create ProcedureRun");
  if (!runResponse.data) throw new Error("ProcedureRun create returned no data.");
  if (isExternalCliRun) {
    return {
      ok: true,
      assignmentId: null,
      assignmentStatus: null,
      runId,
      procedureId: definition.id,
      procedureKey: definition.procedureKey,
      procedureVersionId: version.id,
      procedureVersionNumber: Number(version.versionNumber ?? 1),
      executionMode,
    };
  }
  const assignmentTypeKey = "procedure.run";
  const queueKey = `${assignmentTypeKey}#${definition.id}`;
  const assignmentCreate = await client.models.Assignment.create({
    id: assignmentId,
    assignmentTypeKey,
    queueKey,
    queueStatusKey: `${queueKey}#open`,
    status: "open",
    title: normalizeOptionalString(event.arguments.title) ?? `Run ${definition.title}`,
    summary: normalizeOptionalString(event.arguments.summary) ?? `Procedure ${definition.procedureKey} queued`,
    assigneeType: null,
    assigneeId: null,
    assigneeKey: null,
    claimedAt: null,
    claimExpiresAt: null,
    completedAt: null,
    canceledAt: null,
    sourceSnapshotId: runId,
    importRunId: null,
    createdBy: actorLabel,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "assignments",
  } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(assignmentCreate.errors, "create Assignment");
  if (!assignmentCreate.data?.id) throw new Error("Assignment create returned no id.");
  const createdEventId = `assignment-event-${assignmentId}-created-${now.replace(/[^0-9TZ]/g, "")}-${randomUUID().slice(0, 6)}`;
  const createdEvent = await client.models.AssignmentEvent.create({
    id: createdEventId,
    assignmentId,
    assignmentTypeKey,
    queueKey,
    eventType: "created",
    fromStatus: null,
    toStatus: "open",
    actorSub,
    actorLabel,
    note: `Procedure run created for ${definition.procedureKey}.`,
    createdAt: now,
  } as never, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(createdEvent.errors, "create AssignmentEvent created");

  let assignmentStatus = "open";
  if (IMMEDIATE_ASSIGNMENT_TYPES.has(assignmentTypeKey)) {
    const claimResult: { data?: { status?: string | null } | null; errors?: DataClientErrors } = await (client.mutations.claimAssignment as any)({
      assignmentId,
      actorLabel,
      assigneeType: "system",
      assigneeId: actorSub ?? "system",
      assigneeKey: `system#${actorSub ?? "procedure-runner"}`,
      note: `Immediate execution dispatch for ${definition.procedureKey}.`,
    }, { authMode: LAMBDA_DATA_AUTH_MODE });
    assertNoDataErrors(claimResult.errors, "claimAssignment immediate dispatch");
    assignmentStatus = normalizeOptionalString(claimResult.data?.status) ?? "open";
  }
  const assignment = await getRequiredRecord(client.models.Assignment, assignmentId as string, "Assignment");
  return {
    ok: true,
    assignmentId,
    assignmentStatus: normalizeOptionalString(assignment.status) ?? assignmentStatus,
    runId,
    procedureId: definition.id,
    procedureKey: definition.procedureKey,
    procedureVersionId: version.id,
    procedureVersionNumber: Number(version.versionNumber ?? 1),
  };
}

async function getProcedureRun(args: Record<string, unknown>) {
  const client = await getDataClient();
  const runId = normalizeRequiredString(args.id, "id");
  const run = await getRequiredRecord(client.models.ProcedureRun, runId, "ProcedureRun");
  const assignment = normalizeOptionalString(run.assignmentId)
    ? await getOptionalRecord(client.models.Assignment, run.assignmentId, "Assignment")
    : null;
  return { ...run, assignment };
}

async function listProcedureRunsByProcedure(args: Record<string, unknown>) {
  const client = await getDataClient();
  const procedureId = normalizeRequiredString(args.procedureId, "procedureId");
  const runs = await listProcedureRunsByProcedureId(client, procedureId);
  return {
    items: runs.sort((left, right) => String(right.requestedAt ?? "").localeCompare(String(left.requestedAt ?? ""))),
  };
}

async function resolveDefinition(client: DataClient, input: Record<string, unknown>): Promise<any | null> {
  const procedureId = normalizeOptionalString(input.procedureId);
  if (procedureId) return await getOptionalRecord(client.models.ProcedureDefinition, procedureId, "ProcedureDefinition");
  const procedureKey = normalizeOptionalString(input.procedureKey);
  return await getProcedureDefinitionByKey(client, procedureKey);
}

async function getProcedureDefinitionByKey(client: DataClient, procedureKey: string | null): Promise<any | null> {
  if (!procedureKey) return null;
  const model = client.models.ProcedureDefinition as any;
  if (typeof model.listProcedureDefinitionsByKeyAndUpdatedAt === "function") {
    const response: DataClientResult<any[]> = await model.listProcedureDefinitionsByKeyAndUpdatedAt(
      { procedureKey },
      { limit: 1, sortDirection: "DESC" },
    );
    assertNoDataErrors(response.errors, "list ProcedureDefinitionsByKeyAndUpdatedAt");
    const items = response.data ?? [];
    return items[0] ?? null;
  }
  const all = await listProcedureDefinitionsPage(client);
  return all.find((entry) => normalizeOptionalString(entry.procedureKey) === procedureKey) ?? null;
}

async function listProcedureDefinitionsPage(client: DataClient): Promise<any[]> {
  return await listModelPages((client.models.ProcedureDefinition as any));
}

async function listProcedureVersionsPage(client: DataClient): Promise<any[]> {
  return await listModelPages((client.models.ProcedureVersion as any));
}

async function listProcedureRunsPage(client: DataClient): Promise<any[]> {
  return await listModelPages((client.models.ProcedureRun as any));
}

async function listProcedureVersionsByProcedure(client: DataClient, procedureId: string): Promise<any[]> {
  const model = client.models.ProcedureVersion as any;
  if (typeof model.listProcedureVersionsByProcedureAndVersion === "function") {
    return await listByIndexPages(model.listProcedureVersionsByProcedureAndVersion, { procedureId });
  }
  const all = await listProcedureVersionsPage(client);
  return all.filter((entry) => normalizeOptionalString(entry.procedureId) === procedureId);
}

async function listProcedureRunsByProcedureId(client: DataClient, procedureId: string): Promise<any[]> {
  const model = client.models.ProcedureRun as any;
  if (typeof model.listProcedureRunsByProcedureAndRequestedAt === "function") {
    return await listByIndexPages(model.listProcedureRunsByProcedureAndRequestedAt, { procedureId });
  }
  const all = await listProcedureRunsPage(client);
  return all.filter((entry) => normalizeOptionalString(entry.procedureId) === procedureId);
}

async function listModelPages(model: any): Promise<any[]> {
  const rows: any[] = [];
  let nextToken: string | null | undefined;
  do {
    const response: DataClientResult<any[]> = await model.list({ authMode: LAMBDA_DATA_AUTH_MODE, limit: 200, nextToken });
    assertNoDataErrors(response.errors, `list ${model.name ?? "model"}`);
    rows.push(...(response.data ?? []));
    nextToken = response.nextToken;
  } while (nextToken);
  return rows;
}

async function listByIndexPages(query: (input: Record<string, unknown>, options: Record<string, unknown>) => Promise<DataClientResult<any[]>>, input: Record<string, unknown>): Promise<any[]> {
  const rows: any[] = [];
  let nextToken: string | null | undefined;
  do {
    const response = await query(input, { authMode: LAMBDA_DATA_AUTH_MODE, limit: 200, nextToken });
    assertNoDataErrors(response.errors, "indexed list query");
    rows.push(...(response.data ?? []));
    nextToken = response.nextToken;
  } while (nextToken);
  return rows;
}

function validateJsonSchemaInput(schema: Record<string, unknown>, input: Record<string, unknown>): { ok: true; normalizedInput: Record<string, unknown> } | { ok: false; error: string } {
  const required = arrayOfStrings(schema.required);
  for (const key of required) {
    if (!(key in input) || input[key] === null || input[key] === undefined || input[key] === "") {
      return { ok: false, error: `missing required parameter '${key}'` };
    }
  }
  const properties = objectValue(schema.properties);
  for (const [key, propertySchemaUnknown] of Object.entries(properties)) {
    if (!(key in input)) continue;
    const propertySchema = objectValue(propertySchemaUnknown);
    const expectedType = normalizeOptionalString(propertySchema.type);
    if (!expectedType) continue;
    const value = input[key];
    const valid = (
      (expectedType === "string" && typeof value === "string")
      || (expectedType === "number" && typeof value === "number")
      || (expectedType === "integer" && typeof value === "number" && Number.isInteger(value))
      || (expectedType === "boolean" && typeof value === "boolean")
      || (expectedType === "array" && Array.isArray(value))
      || (expectedType === "object" && value !== null && typeof value === "object" && !Array.isArray(value))
    );
    if (!valid) return { ok: false, error: `parameter '${key}' must be ${expectedType}` };
  }
  return { ok: true, normalizedInput: input };
}

function requireAdmin(event: ProcedureEvent): void {
  const claims = objectValue(event.identity?.claims);
  const groups = [...claimGroups(claims["cognito:groups"]), ...claimGroups(claims.groups)];
  if (groups.includes("admin")) return;
  throw new Error("Admin role required.");
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

async function getRequiredRecord(
  model: { get(input: { id: string }, options?: Record<string, unknown>): Promise<{ data?: unknown | null; errors?: DataClientErrors }> },
  id: string,
  modelName: string,
): Promise<any> {
  const response = await model.get({ id }, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(response.errors, `get ${modelName}`);
  if (!response.data) throw new Error(`${modelName} ${id} was not found.`);
  return response.data;
}

async function getOptionalRecord(
  model: { get(input: { id: string }, options?: Record<string, unknown>): Promise<{ data?: unknown | null; errors?: DataClientErrors }> },
  id: string,
  modelName: string,
): Promise<any | null> {
  const response = await model.get({ id }, { authMode: LAMBDA_DATA_AUTH_MODE });
  assertNoDataErrors(response.errors, `get ${modelName}`);
  return response.data ?? null;
}

function assertNoDataErrors(errors: DataClientErrors, operation: string): void {
  if (!errors?.length) return;
  throw new Error(`${operation} failed: ${errors.map(formatDataError).join("; ")}`);
}

function formatDataError(error: { message?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  return error?.message ?? "GraphQL data operation failed.";
}

function getIdentitySub(event: ProcedureEvent): string | null {
  const identity = event.identity as { sub?: string | null; claims?: Record<string, unknown> } | null | undefined;
  return normalizeOptionalString(identity?.sub) ?? normalizeOptionalString(identity?.claims?.sub);
}

function getIdentityLabel(event: ProcedureEvent): string | null {
  const identity = event.identity as { username?: string | null; claims?: Record<string, unknown> } | null | undefined;
  return normalizeOptionalString(identity?.claims?.email)
    ?? normalizeOptionalString(identity?.claims?.name)
    ?? normalizeOptionalString(identity?.username)
    ?? getIdentitySub(event);
}

function normalizeRequiredString(value: unknown, field: string): string {
  const normalized = normalizeOptionalString(value);
  if (!normalized) throw new Error(`${field} is required.`);
  return normalized;
}

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeOptionalBoolean(value: unknown, fallback: boolean): boolean {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return fallback;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function normalizeJson(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    throw new Error("JSON input must be an object.");
  }
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  return {};
}

function normalizeOptionalJson(value: unknown): Record<string, unknown> | null {
  if (value === null || value === undefined || value === "") return null;
  return normalizeJson(value);
}

function toAwsJson(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return JSON.stringify(value);
}

function arrayOfStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => normalizeOptionalString(entry)).filter((entry): entry is string => Boolean(entry));
}

function safeId(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    || "procedure";
}

function hashShort(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(value))
    .digest("hex")
    .slice(0, 16);
}

function groupBy<T>(rows: T[], keyFn: (entry: T) => string): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const row of rows) {
    const key = keyFn(row);
    const current = map.get(key) ?? [];
    current.push(row);
    map.set(key, current);
  }
  return map;
}
