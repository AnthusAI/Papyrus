import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";
import { actingFor, buildEventTenantContext, currentTenantContext } from "../shared/tenant-context";
import { newsroomSummaryPayloadId, tenantScopedClient } from "../shared/tenant-scoped-client";
import { putJsonModelPayload, readJsonModelPayload } from "../shared/model-payloads";

type DataClient = ReturnType<typeof generateClient<Schema>>;
type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;

const NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND = "knowledgeRawPayload";
const SUMMARY_STALE_AFTER_MS = 15 * 60 * 1000;
let clientPromise: Promise<DataClient> | null = null;

export const handler = async (
  event: Parameters<Schema["getNewsroomSummary"]["functionHandler"]>[0] | Parameters<Schema["updateNewsroomSummary"]["functionHandler"]>[0],
) => {
  const context = buildEventTenantContext(event);   // one context per call; a shared stack refuses before any read
  return actingFor(context, () => {
    const fieldName = typeof event.info?.fieldName === "string" ? event.info.fieldName : "getNewsroomSummary";
    if (fieldName === "updateNewsroomSummary" || "delta" in event.arguments) {
      return updateNewsroomSummary(event as Parameters<Schema["updateNewsroomSummary"]["functionHandler"]>[0]);
    }
    return getNewsroomSummary();
  });
};

async function getNewsroomSummary() {
  const client = await getDataClient();
  const response = await client.models.KnowledgeRawPayload.get({ id: newsroomSummaryPayloadId(currentTenantContext()) });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const payload = await readNewsroomSummaryPayload(client);
  return summaryFromPayload(normalizeSummaryPayload(payload, response.data?.updatedAt ?? new Date().toISOString()));
}

async function updateNewsroomSummary(event: Parameters<Schema["updateNewsroomSummary"]["functionHandler"]>[0]) {
  const client = await getDataClient();
  const now = new Date().toISOString();
  const response = await client.models.KnowledgeRawPayload.get({ id: newsroomSummaryPayloadId(currentTenantContext()) });
  assertNoDataErrors(response.errors, "get Newsroom summary snapshot");
  const currentPayload = normalizeSummaryPayload(await readNewsroomSummaryPayload(client), now);
  const delta = parseJsonObject(event.arguments.delta);
  const nextPayload = applySummaryDelta(currentPayload, delta, {
    now,
    actorLabel: normalizeOptionalString(event.arguments.actorLabel),
    reason: normalizeOptionalString(event.arguments.reason),
  });
  await upsertNewsroomSummaryPayload(client, nextPayload, response.data, now);
  return summaryFromPayload(nextPayload);
}

async function getDataClient(): Promise<DataClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const { resourceConfig, libraryOptions } = await getAmplifyDataClientConfig(process.env as never);
      Amplify.configure(resourceConfig, libraryOptions);
      return generateClient<Schema>();
    })();
  }
  return tenantScopedClient(await clientPromise, currentTenantContext());
}

async function upsertNewsroomSummaryPayload(
  client: DataClient,
  payload: ReturnType<typeof normalizeSummaryPayload>,
  current: any,
  now: string,
): Promise<void> {
  const input = {
    id: newsroomSummaryPayloadId(currentTenantContext()),
    ownerType: "newsroom",
    ownerId: "newsroom",
    payloadKind: "summary-snapshot",
    importRunId: normalizeOptionalString(payload.latestImportRun?.id),
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
    { ownerKind: NEWSROOM_SUMMARY_PAYLOAD_OWNER_KIND, ownerId: newsroomSummaryPayloadId(currentTenantContext()), importRunId: input.importRunId },
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
    newsroomSummaryPayloadId(currentTenantContext()),
    "raw_payload",
    "summary-snapshot",
  );
}

function summaryFromPayload(payload: ReturnType<typeof normalizeSummaryPayload>) {
  return {
    generatedAt: payload.generatedAt,
    staleAt: payload.staleAt,
    source: payload.source,
    latestImportRun: payload.latestImportRun,
    counts: payload.counts,
    facets: payload.facets,
    assignmentStatusCounts: payload.assignmentStatusCounts,
    assignmentTypeCounts: payload.assignmentTypeCounts,
    referenceStatusCounts: payload.referenceStatusCounts,
    messageKindCounts: payload.messageKindCounts,
    messageDomainCounts: payload.messageDomainCounts,
  };
}

function applySummaryDelta(
  payload: ReturnType<typeof normalizeSummaryPayload>,
  delta: Record<string, unknown>,
  options: { now: string; actorLabel: string | null; reason: string | null },
) {
  const next = {
    ...payload,
    counts: { ...payload.counts },
    facets: cloneFacets(payload.facets),
    assignmentStatusCounts: { ...payload.assignmentStatusCounts },
    assignmentTypeCounts: { ...payload.assignmentTypeCounts },
    referenceStatusCounts: { ...payload.referenceStatusCounts },
    messageKindCounts: { ...payload.messageKindCounts },
    messageDomainCounts: { ...payload.messageDomainCounts },
  };
  next.generatedAt = options.now;
  next.staleAt = new Date(Date.parse(options.now) + SUMMARY_STALE_AFTER_MS).toISOString();
  next.source = normalizeOptionalString(delta.source) ?? "incremental";
  if (options.actorLabel) next.actorLabel = options.actorLabel;
  if (options.reason) next.reason = options.reason;
  const latestImportRun = parseJsonObject(delta.latestImportRun);
  if (Object.keys(latestImportRun).length) next.latestImportRun = latestImportRun;
  const facetDeltas = parseJsonObject(delta.facetDeltas);
  applyNumberDeltas(next.counts, delta.countDeltas);
  if (!hasFacetDelta(facetDeltas, "assignments", "byStatus")) {
    applyNumberDeltas(next.facets.assignments.byStatus, delta.assignmentStatusDeltas);
  }
  if (!hasFacetDelta(facetDeltas, "assignments", "byType")) {
    applyNumberDeltas(next.facets.assignments.byType, delta.assignmentTypeDeltas);
  }
  if (!hasFacetDelta(facetDeltas, "references", "byCurationStatus")) {
    applyNumberDeltas(next.facets.references.byCurationStatus, delta.referenceStatusDeltas);
  }
  if (!hasFacetDelta(facetDeltas, "messages", "byKind")) {
    applyNumberDeltas(next.facets.messages.byKind, delta.messageKindDeltas);
  }
  if (!hasFacetDelta(facetDeltas, "messages", "byDomain")) {
    applyNumberDeltas(next.facets.messages.byDomain, delta.messageDomainDeltas);
  }
  applyFacetDeltas(next.facets, delta.facetDeltas);
  syncCompatibilityCounts(next);
  return next;
}

function normalizeSummaryPayload(value: unknown, now: string) {
  const parsed = parseJsonObject(value);
  const facets = normalizeFacets(parsed.facets, parsed);
  return {
    generatedAt: normalizeOptionalString(parsed.generatedAt) ?? now,
    staleAt: normalizeOptionalString(parsed.staleAt) ?? now,
    source: normalizeOptionalString(parsed.source) ?? "missing",
    actorLabel: normalizeOptionalString(parsed.actorLabel),
    reason: normalizeOptionalString(parsed.reason),
    latestImportRun: parseJsonObject(parsed.latestImportRun),
    counts: numberRecord(parsed.counts),
    facets,
    assignmentStatusCounts: { ...facets.assignments.byStatus },
    assignmentTypeCounts: { ...facets.assignments.byType },
    referenceStatusCounts: { ...facets.references.byCurationStatus },
    messageKindCounts: { ...facets.messages.byKind },
    messageDomainCounts: { ...facets.messages.byDomain },
  };
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

function normalizeFacets(value: unknown, legacy: Record<string, unknown>) {
  const facets = createEmptyFacets();
  const parsed = parseJsonObject(value);
  mergeFacetSection(facets.assignments, parsed.assignments, ["statusByType", "statusBySection", "typeBySection"]);
  mergeFacetSection(facets.messages, parsed.messages, ["domainByKind"]);
  mergeFacetSection(facets.modelAttachments, parsed.modelAttachments);
  mergeFacetSection(facets.references, parsed.references, ["statusByCorpus"]);
  mergeFacetSection(facets.semanticNodes, parsed.semanticNodes);
  mergeFacetSection(facets.semanticRelations, parsed.semanticRelations);
  mergeFacetSection(facets.imports, parsed.imports);
  Object.assign(facets.assignments.byStatus, numberRecord(legacy.assignmentStatusCounts));
  Object.assign(facets.assignments.byType, numberRecord(legacy.assignmentTypeCounts));
  Object.assign(facets.references.byCurationStatus, numberRecord(legacy.referenceStatusCounts));
  Object.assign(facets.messages.byKind, numberRecord(legacy.messageKindCounts));
  Object.assign(facets.messages.byDomain, numberRecord(legacy.messageDomainCounts));
  return facets;
}

function mergeFacetSection(target: Record<string, any>, source: unknown, nestedKeys: string[] = []): void {
  const parsed = parseJsonObject(source);
  for (const key of Object.keys(target)) {
    target[key] = nestedKeys.includes(key) ? nestedNumberRecord(parsed[key]) : numberRecord(parsed[key]);
  }
}

function cloneFacets(value: ReturnType<typeof createEmptyFacets>) {
  return JSON.parse(JSON.stringify(value)) as ReturnType<typeof createEmptyFacets>;
}

function nestedNumberRecord(value: unknown): Record<string, Record<string, number>> {
  const parsed = parseJsonObject(value);
  const result: Record<string, Record<string, number>> = {};
  for (const [key, nested] of Object.entries(parsed)) {
    const record = numberRecord(nested);
    if (Object.keys(record).length) result[key] = record;
  }
  return result;
}

function applyFacetDeltas(target: Record<string, any>, deltas: unknown): void {
  const parsed = parseJsonObject(deltas);
  for (const [sectionKey, sectionDeltas] of Object.entries(parsed)) {
    const section = target[sectionKey];
    if (!section || typeof section !== "object") continue;
    const parsedSection = parseJsonObject(sectionDeltas);
    for (const [facetKey, facetDelta] of Object.entries(parsedSection)) {
      if (!section[facetKey] || typeof section[facetKey] !== "object") continue;
      if (Object.values(parseJsonObject(facetDelta)).some((entry) => entry && typeof entry === "object" && !Array.isArray(entry))) {
        applyNestedNumberDeltas(section[facetKey], facetDelta);
      } else {
        applyNumberDeltas(section[facetKey], facetDelta);
      }
    }
  }
}

function applyNestedNumberDeltas(target: Record<string, Record<string, number>>, deltas: unknown): void {
  const parsed = parseJsonObject(deltas);
  for (const [outerKey, innerDeltas] of Object.entries(parsed)) {
    if (!target[outerKey] || typeof target[outerKey] !== "object") target[outerKey] = {};
    applyNumberDeltas(target[outerKey], innerDeltas);
    if (!Object.keys(target[outerKey]).length) delete target[outerKey];
  }
}

function hasFacetDelta(facetDeltas: Record<string, unknown>, sectionKey: string, facetKey: string): boolean {
  const section = parseJsonObject(facetDeltas[sectionKey]);
  return Boolean(section[facetKey]);
}

function syncCompatibilityCounts(payload: ReturnType<typeof normalizeSummaryPayload>): void {
  payload.assignmentStatusCounts = { ...payload.facets.assignments.byStatus };
  payload.assignmentTypeCounts = { ...payload.facets.assignments.byType };
  payload.referenceStatusCounts = { ...payload.facets.references.byCurationStatus };
  payload.messageKindCounts = { ...payload.facets.messages.byKind };
  payload.messageDomainCounts = { ...payload.facets.messages.byDomain };
}

function applyNumberDeltas(target: Record<string, number>, deltas: unknown): void {
  const parsed = parseJsonObject(deltas);
  for (const [key, delta] of Object.entries(parsed)) {
    const numericDelta = Number(delta);
    if (!Number.isFinite(numericDelta)) continue;
    const next = Math.max(0, (target[key] ?? 0) + numericDelta);
    if (next === 0) delete target[key];
    else target[key] = next;
  }
}

function numberRecord(value: unknown): Record<string, number> {
  const parsed = parseJsonObject(value);
  const result: Record<string, number> = {};
  for (const [key, entry] of Object.entries(parsed)) {
    const numeric = Number(entry);
    if (Number.isFinite(numeric)) result[key] = numeric;
  }
  return result;
}

function parseJsonObject(value: unknown): Record<string, any> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, any>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, any> : {};
  } catch {
    return {};
  }
}

async function requireDataResult<T>(promise: Promise<{ data?: T | null; errors?: DataClientErrors }>, operation: string): Promise<T> {
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

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}
