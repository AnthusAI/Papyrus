"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { createLocalPreviewReportingTrail } from "../lib/local-preview-seed";
import { EMPTY_STORY_REPORTING_TRAIL, type StoryReportingTrail, type TrailAssignment, type TrailAttachment, type TrailReference, type TrailThread, type TrailVersion } from "../lib/story-reporting-trail";
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

/** Reads the whole reporting trail of one story from the backend; the local preview serves a snapshot instead. */
export async function loadStoryReportingTrail(lineageId: string, itemId: string): Promise<StoryReportingTrail> {
  if (isLocalPreviewEnabled()) return createLocalPreviewReportingTrail(lineageId);
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as GraphqlClient;
  const [versionRows, assignmentRows, attachmentRows, relationRows] = await Promise.all([
    listAll(client, "listItemsByLineageAndVersion", "id versionNumber versionState status stage headline title changeReason versionCreatedBy versionCreatedAt updatedAt", ", $lineageId: ID!", ", lineageId: $lineageId", { lineageId }).catch(() => []),
    listAll(client, "listAssignmentsByItemLineageAndCreatedAt", "id title assignmentTypeKey status assigneeKey summary createdAt", ", $itemLineageId: ID!", ", itemLineageId: $itemLineageId", { itemLineageId: lineageId }).catch(() => []),
    listAll(client, "listModelAttachmentsByOwnerRoleAndSortKey", "id role filename mediaType byteSize", ", $ownerId: ID!", ", ownerId: $ownerId", { ownerId: itemId }).catch(() => []),
    listAll(client, "listSemanticRelations", "id predicate subjectKind subjectLineageId objectKind objectId objectLineageId", ", $filter: ModelSemanticRelationFilterInput", ", filter: $filter", { filter: { or: [{ subjectLineageId: { eq: lineageId } }, { objectLineageId: { eq: lineageId } }] } }).catch(() => []),
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
    const messageRows = await listAll(client, "listMessagesByThreadAndSequence", "id messageKind authorLabel summary content createdAt", ", $threadId: ID!", ", threadId: $threadId", { threadId: row.id }).catch(() => []);
    return { id: String(row.id), title: text(row.title), threadKind: text(row.threadKind), summary: text(row.summary), messages: messageRows.map(message => ({ id: String(message.id), messageKind: text(message.messageKind), authorLabel: text(message.authorLabel), summary: text(message.summary), content: text(message.content), createdAt: String(message.createdAt ?? "") })) };
  }));
  const references: TrailReference[] = relationRows.filter(relation => relation.objectKind === "reference" || relation.subjectKind === "reference").map(relation => ({
    relationId: String(relation.id), predicate: String(relation.predicate ?? ""), referenceId: String(relation.objectKind === "reference" ? relation.objectId : relation.subjectLineageId ?? ""), referenceLineageId: text(relation.objectKind === "reference" ? relation.objectLineageId : relation.subjectLineageId), title: null, sourceUri: null,
  }));
  const attachments: TrailAttachment[] = attachmentRows.map(row => ({ id: String(row.id), role: text(row.role), filename: text(row.filename), mediaType: text(row.mediaType), byteSize: typeof row.byteSize === "number" ? row.byteSize : null }));
  return { ...EMPTY_STORY_REPORTING_TRAIL, versions, assignments, threads, references, attachments };
}
