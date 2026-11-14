"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { createLocalPreviewReportingTrail, createLocalPreviewStoriesForReference } from "../lib/local-preview-seed";
import { AGENT_NOTE_ROLE, EMPTY_STORY_REPORTING_TRAIL, agentNoteOf, referencesByRole, siteNameOf, stageMovesOf, type ReferenceStory, type StoryReportingTrail, type TrailAgentNote, type TrailAssignment, type TrailAttachment, type TrailReference, type TrailThread, type TrailVersion } from "../lib/story-reporting-trail";
import { researchPacketOf, type ResearchPacketView } from "../lib/research-packet";
import { configureAmplifyClient } from "./amplify-client-provider";
import { loadModelPayloadsForOwner } from "./news-desk-taxonomy-client";

type GraphqlResponse = { data?: Record<string, { items?: Record<string, unknown>[] | null; nextToken?: string | null } | null> | null; errors?: { message?: string }[] | null };
export type GraphqlClient = { graphql: (options: Record<string, unknown>) => Promise<GraphqlResponse> };

const USER_POOL = "userPool";
const PAGE_LIMIT = 200;

async function listAll(client: GraphqlClient, field: string, selection: string, variableDeclarations: string, fieldArguments: string, variables: Record<string, unknown>): Promise<Record<string, unknown>[]> {
  const rows: Record<string, unknown>[] = [];
  let nextToken: string | null = null;
  do {
    const response: GraphqlResponse = await client.graphql({
      query: `query ($limit: Int, $nextToken: String${variableDeclarations}) { ${field}(limit: $limit, nextToken: $nextToken${fieldArguments}) { items { ${selection} } nextToken } }`,
      variables: { ...variables, limit: PAGE_LIMIT, nextToken },
      authMode: USER_POOL,
    });
    if (response.errors?.length) throw new Error(response.errors.map(error => error.message ?? "GraphQL error").join("; "));
    const connection = response.data?.[field];
    rows.push(...((connection?.items ?? []).filter(Boolean) as Record<string, unknown>[]));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return rows;
}

const text = (value: unknown): string | null => typeof value === "string" ? value : null;

function parseMetadata(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try { const parsed = JSON.parse(value); return typeof parsed === "object" && parsed ? parsed as Record<string, unknown> : {}; } catch { return {}; }
  }
  return typeof value === "object" && value ? value as Record<string, unknown> : {};
}

async function getReference(client: GraphqlClient, referenceId: string): Promise<Record<string, unknown> | null> {
  try {
    const response = await client.graphql({ query: "query ($id: ID!) { getReference(id: $id) { id title sourceUri } }", variables: { id: referenceId }, authMode: USER_POOL });
    return (response.data?.getReference as unknown as Record<string, unknown> | null) ?? null;
  } catch {
    return null;
  }
}

function relationRole(value: unknown): TrailReference["role"] {
  return value === "based_on" ? "based_on" : value === "cited" ? "cited" : "consulted";
}

/** The Reference's preview image address and site name, from its `preview` attachment (nothing is downloaded). */
async function getPreview(client: GraphqlClient, referenceLineageId: string): Promise<{ imageUrl: string | null; siteName: string | null }> {
  try {
    const rows = await listAll(client, "listReferenceAttachmentsByReferenceLineageAndSortKey", "id role sourceUri filename metadata", ", $referenceLineageId: ID!", ", referenceLineageId: $referenceLineageId", { referenceLineageId });
    const preview = rows.find(row => row.role === "preview");
    const address = text(preview?.sourceUri);
    return { imageUrl: address && /^https?:\/\//i.test(address) ? address : null, siteName: text(parseMetadata(preview?.metadata).siteName) ?? text(preview?.filename) };
  } catch {
    return { imageUrl: null, siteName: null };
  }
}

/** The editor's direction, from a research assignment's `metadata` attachment (the Assignment model has no column for it). */
async function getDirection(assignmentId: string): Promise<string | null> {
  try {
    const payloads = await loadModelPayloadsForOwner("assignment", assignmentId, ["metadata"]);
    const direction = payloads.map(payload => parseMetadata(payload.json ?? payload.text).direction).find(value => typeof value === "string" && value.trim());
    return typeof direction === "string" ? direction : null;
  } catch {
    return null;
  }
}

/** The packet a research assignment produced: the Message on its `produces` relation, and that Message's `metadata` attachment. Read-only; no Message thread is touched. */
async function getPacket(client: GraphqlClient, assignmentId: string): Promise<ResearchPacketView | null> {
  try {
    const relations = await listAll(client, "listSemanticRelationsBySubjectState", "id predicate objectKind objectId", ", $subjectStateKey: String!", ", subjectStateKey: $subjectStateKey", { subjectStateKey: `assignment#${assignmentId}#current` });
    const produced = relations.filter(relation => relation.predicate === "produces" && relation.objectKind === "message").map(relation => String(relation.objectId));
    for (const messageId of produced) {
      const payloads = await loadModelPayloadsForOwner("message", messageId, ["metadata"]);
      for (const payload of payloads) {
        const packet = researchPacketOf(parseMetadata(payload.json ?? payload.text).research);
        if (packet) return packet;
      }
    }
    return null;
  } catch {
    return null;
  }
}

/** The AI agent notes of the story, oldest first: `agent_note` attachments owned by its first version record. A note that cannot be read is left out. */
async function getAgentNotes(ownerId: string | null): Promise<TrailAgentNote[]> {
  if (!ownerId) return [];
  try {
    const payloads = await loadModelPayloadsForOwner("item", ownerId, [AGENT_NOTE_ROLE]);
    return payloads
      .flatMap(payload => { const note = agentNoteOf(payload.attachment.id, payload.json, payload.attachment.createdAt); return note ? [note] : []; })
      .sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  } catch {
    return [];
  }
}

/** The stories whose `uses_evidence` link names this Reference, each with its working title and stage. */
export async function loadStoriesBasedOnReference(referenceLineageId: string, demo = false): Promise<ReferenceStory[]> {
  if (demo || isLocalPreviewEnabled()) return createLocalPreviewStoriesForReference(referenceLineageId);
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as GraphqlClient;
  const relations = await listAll(client, "listSemanticRelationsByObjectState", "id predicate subjectKind subjectId subjectLineageId metadata", ", $objectStateKey: String!", ", objectStateKey: $objectStateKey", { objectStateKey: `reference#${referenceLineageId}#current` });
  const stories = relations.filter(relation => relation.predicate === "uses_evidence" && relation.subjectKind === "item");
  const rows = await Promise.all(stories.map(async relation => {
    const lineageId = String(relation.subjectLineageId ?? relation.subjectId);
    const versions = await listAll(client, "listItemsByLineageAndVersion", "id versionNumber versionState stage headline title", ", $lineageId: ID!", ", lineageId: $lineageId", { lineageId }).catch(() => []);
    const current = versions.find(version => version.versionState === "current") ?? versions.sort((left, right) => Number(right.versionNumber ?? 0) - Number(left.versionNumber ?? 0))[0];
    return {
      relationId: String(relation.id), itemId: String(current?.id ?? relation.subjectId), lineageId, title: text(current?.headline) ?? text(current?.title), stage: text(current?.stage),
      role: relationRole(parseMetadata(relation.metadata).role),
    } satisfies ReferenceStory;
  }));
  return rows;
}

/** Reads the whole reporting trail of one story from the backend; the local preview serves a snapshot instead. */
function defaultClient(): GraphqlClient {
  configureAmplifyClient();
  return generateClient<Schema>() as unknown as GraphqlClient;
}

/**
 * The newest version of a story: one indexed read of one row (the lineage index sorted by version number, newest first). The editor needs
 * only this to say "version 2 of 5"; it used to load the whole reporting trail for it.
 */
export async function loadNewestStoryVersion(lineageId: string, demo = false, client?: GraphqlClient): Promise<{ id: string; versionNumber: number } | null> {
  if (!client && (demo || isLocalPreviewEnabled())) {
    const newest = createLocalPreviewReportingTrail(lineageId).versions[0];
    return newest ? { id: newest.id, versionNumber: newest.versionNumber } : null;
  }
  const graphql = client ?? defaultClient();
  const response = await graphql.graphql({
    query: "query ($lineageId: ID!, $limit: Int) { listItemsByLineageAndVersion(lineageId: $lineageId, sortDirection: DESC, limit: $limit) { items { id versionNumber } nextToken } }",
    variables: { lineageId, limit: 1 },
    authMode: USER_POOL,
  });
  if (response.errors?.length) throw new Error(response.errors.map(error => error.message ?? "GraphQL error").join("; "));
  const newest = response.data?.listItemsByLineageAndVersion?.items?.find(Boolean);
  return newest ? { id: String(newest.id), versionNumber: Number(newest.versionNumber ?? 0) } : null;
}

export async function loadStoryReportingTrail(lineageId: string, itemId: string, demo = false, injectedClient?: GraphqlClient): Promise<StoryReportingTrail> {
  if (!injectedClient && (demo || isLocalPreviewEnabled())) return createLocalPreviewReportingTrail(lineageId);
  const client = injectedClient ?? defaultClient();
  const [versionRows, assignmentRows, attachmentRows, relationRows] = await Promise.all([
    listAll(client, "listItemsByLineageAndVersion", "id versionNumber versionState status stage headline title changeReason versionCreatedBy versionCreatedAt updatedAt metadata", ", $lineageId: ID!", ", lineageId: $lineageId", { lineageId }).catch(() => []),
    listAll(client, "listAssignmentsByItemLineageAndCreatedAt", "id title assignmentTypeKey status assigneeKey summary createdAt", ", $itemLineageId: ID!", ", itemLineageId: $itemLineageId", { itemLineageId: lineageId }).catch(() => []),
    listAll(client, "listModelAttachmentsByOwnerRoleAndSortKey", "id role filename mediaType byteSize", ", $ownerId: ID!", ", ownerId: $ownerId", { ownerId: itemId }).catch(() => []),
    // The story's References are relations whose subject is the story: the subject-state index, as `papyrus stories references` reads them
    // (story_reporting.story_references). A filtered listSemanticRelations here was a scan of the whole relation table on every open.
    listAll(client, "listSemanticRelationsBySubjectState", "id predicate subjectKind subjectLineageId objectKind objectId objectLineageId metadata", ", $subjectStateKey: String!", ", subjectStateKey: $subjectStateKey", { subjectStateKey: `item#${lineageId}#current` }).catch(() => []),
  ]);
  const versions: TrailVersion[] = versionRows.map(row => ({
    id: String(row.id), versionNumber: Number(row.versionNumber ?? 0), versionState: text(row.versionState), status: text(row.status), stage: text(row.stage),
    headline: text(row.headline) ?? text(row.title), changeReason: text(row.changeReason), versionCreatedBy: text(row.versionCreatedBy), versionCreatedAt: text(row.versionCreatedAt), updatedAt: text(row.updatedAt),
  })).sort((left, right) => right.versionNumber - left.versionNumber);
  const assignments: TrailAssignment[] = await Promise.all(assignmentRows.map(async row => {
    const eventRows = await listAll(client, "listAssignmentEventsByAssignmentAndCreatedAt", "id eventType fromStatus toStatus actorLabel note createdAt", ", $assignmentId: ID!", ", assignmentId: $assignmentId", { assignmentId: row.id }).catch(() => []);
    const research = row.assignmentTypeKey === "research.multi";
    const [direction, packet] = research ? await Promise.all([getDirection(String(row.id)), row.status === "completed" ? getPacket(client, String(row.id)) : Promise.resolve(null)]) : [null, null];
    return {
      id: String(row.id), title: String(row.title ?? ""), assignmentTypeKey: String(row.assignmentTypeKey ?? ""), status: String(row.status ?? ""), assigneeKey: text(row.assigneeKey), summary: text(row.summary), createdAt: String(row.createdAt ?? ""), direction, packet,
      events: eventRows.map(event => ({ id: String(event.id), eventType: String(event.eventType ?? ""), fromStatus: text(event.fromStatus), toStatus: text(event.toStatus), actorLabel: text(event.actorLabel), note: text(event.note), createdAt: String(event.createdAt ?? "") })),
    };
  }));
  const anchorFilters = [{ primaryAnchorLineageId: { eq: lineageId } }, ...assignments.map(assignment => ({ primaryAnchorId: { eq: assignment.id } }))];
  const threadRows = await listAll(client, "listMessageThreads", "id title threadKind summary", ", $filter: ModelMessageThreadFilterInput", ", filter: $filter", { filter: { or: anchorFilters } }).catch(() => []);
  const threads: TrailThread[] = await Promise.all(threadRows.map(async row => {
    const messageRows = await listAll(client, "listMessagesByThreadAndSequence", "id messageKind authorLabel summary content createdAt sequenceNumber", ", $threadId: ID!", ", threadId: $threadId", { threadId: row.id }).catch(() => []);
    return { id: String(row.id), title: text(row.title), threadKind: text(row.threadKind), summary: text(row.summary), messages: messageRows.map(message => ({ id: String(message.id), sequenceNumber: typeof message.sequenceNumber === "number" ? message.sequenceNumber : null, messageKind: text(message.messageKind), authorLabel: text(message.authorLabel), summary: text(message.summary), content: text(message.content), createdAt: String(message.createdAt ?? "") })) };
  }));
  const referenceRelations = relationRows.filter(relation => relation.predicate === "uses_evidence" && relation.subjectLineageId === lineageId && relation.objectKind === "reference");
  const references: TrailReference[] = referencesByRole(await Promise.all(referenceRelations.map(async relation => {
    const metadata = parseMetadata(relation.metadata);
    const referenceRow = await getReference(client, String(relation.objectId));
    const preview = await getPreview(client, text(relation.objectLineageId) ?? String(relation.objectId));
    const sourceUri = text(referenceRow?.sourceUri);
    return {
      relationId: String(relation.id), predicate: String(relation.predicate ?? ""), referenceId: String(relation.objectId), referenceLineageId: text(relation.objectLineageId),
      title: text(referenceRow?.title), sourceUri, siteName: siteNameOf(sourceUri, preview.siteName), previewImageUrl: preview.imageUrl,
      role: relationRole(metadata.role), note: text(metadata.note), citationKey: text(metadata.citationKey), addedBy: text(metadata.addedBy), addedAt: text(metadata.addedAt),
    };
  })));
  const firstVersion = [...versionRows].sort((left, right) => Number(left.versionNumber ?? 0) - Number(right.versionNumber ?? 0))[0];
  const agentNotes = await getAgentNotes(firstVersion ? String(firstVersion.id) : null);
  const attachments: TrailAttachment[] = attachmentRows.filter(row => row.role !== AGENT_NOTE_ROLE).map(row => ({ id: String(row.id), role: text(row.role), filename: text(row.filename), mediaType: text(row.mediaType), byteSize: typeof row.byteSize === "number" ? row.byteSize : null }));
  const latestRow = [...versionRows].sort((left, right) => Number(right.versionNumber ?? 0) - Number(left.versionNumber ?? 0))[0];
  return { ...EMPTY_STORY_REPORTING_TRAIL, versions, assignments, threads, references, attachments, stageMoves: stageMovesOf(latestRow?.metadata), agentNotes };
}
