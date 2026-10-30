"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { createLocalPreviewReportingTrail, createLocalPreviewStoriesForReference } from "../lib/local-preview-seed";
import { EMPTY_STORY_REPORTING_TRAIL, referencesByRole, siteNameOf, stageMovesOf, type ReferenceStory, type StoryReportingTrail, type TrailAssignment, type TrailAttachment, type TrailReference, type TrailThread, type TrailVersion } from "../lib/story-reporting-trail";
import { configureAmplifyClient } from "./amplify-client-provider";

type GraphqlResponse = { data?: Record<string, { items?: Record<string, unknown>[] | null; nextToken?: string | null } | null> | null; errors?: { message?: string }[] | null };
type GraphqlClient = { graphql: (options: Record<string, unknown>) => Promise<GraphqlResponse> };

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
export async function loadStoryReportingTrail(lineageId: string, itemId: string, demo = false): Promise<StoryReportingTrail> {
  if (demo || isLocalPreviewEnabled()) return createLocalPreviewReportingTrail(lineageId);
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as GraphqlClient;
  const [versionRows, assignmentRows, attachmentRows, relationRows] = await Promise.all([
    listAll(client, "listItemsByLineageAndVersion", "id versionNumber versionState status stage headline title changeReason versionCreatedBy versionCreatedAt updatedAt metadata", ", $lineageId: ID!", ", lineageId: $lineageId", { lineageId }).catch(() => []),
    listAll(client, "listAssignmentsByItemLineageAndCreatedAt", "id title assignmentTypeKey status assigneeKey summary createdAt", ", $itemLineageId: ID!", ", itemLineageId: $itemLineageId", { itemLineageId: lineageId }).catch(() => []),
    listAll(client, "listModelAttachmentsByOwnerRoleAndSortKey", "id role filename mediaType byteSize", ", $ownerId: ID!", ", ownerId: $ownerId", { ownerId: itemId }).catch(() => []),
    listAll(client, "listSemanticRelations", "id predicate subjectKind subjectLineageId objectKind objectId objectLineageId metadata", ", $filter: ModelSemanticRelationFilterInput", ", filter: $filter", { filter: { or: [{ subjectLineageId: { eq: lineageId } }, { objectLineageId: { eq: lineageId } }] } }).catch(() => []),
  ]);
  const versions: TrailVersion[] = versionRows.map(row => ({
    id: String(row.id), versionNumber: Number(row.versionNumber ?? 0), versionState: text(row.versionState), status: text(row.status), stage: text(row.stage),
    headline: text(row.headline) ?? text(row.title), changeReason: text(row.changeReason), versionCreatedBy: text(row.versionCreatedBy), versionCreatedAt: text(row.versionCreatedAt), updatedAt: text(row.updatedAt),
  })).sort((left, right) => right.versionNumber - left.versionNumber);
  const assignments: TrailAssignment[] = await Promise.all(assignmentRows.map(async row => {
    const eventRows = await listAll(client, "listAssignmentEventsByAssignmentAndCreatedAt", "id eventType fromStatus toStatus actorLabel note createdAt", ", $assignmentId: ID!", ", assignmentId: $assignmentId", { assignmentId: row.id }).catch(() => []);
    return {
      id: String(row.id), title: String(row.title ?? ""), assignmentTypeKey: String(row.assignmentTypeKey ?? ""), status: String(row.status ?? ""), assigneeKey: text(row.assigneeKey), summary: text(row.summary), createdAt: String(row.createdAt ?? ""),
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
  const attachments: TrailAttachment[] = attachmentRows.map(row => ({ id: String(row.id), role: text(row.role), filename: text(row.filename), mediaType: text(row.mediaType), byteSize: typeof row.byteSize === "number" ? row.byteSize : null }));
  const latestRow = [...versionRows].sort((left, right) => Number(right.versionNumber ?? 0) - Number(left.versionNumber ?? 0))[0];
  return { ...EMPTY_STORY_REPORTING_TRAIL, versions, assignments, threads, references, attachments, stageMoves: stageMovesOf(latestRow?.metadata) };
}
