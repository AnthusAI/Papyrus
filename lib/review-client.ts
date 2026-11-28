"use client";

import { generateClient } from "aws-amplify/data";
import { getCurrentUser } from "aws-amplify/auth";
import {
  DECIDED_STATES, answerUpdate, normalizeReviewRow, reviewStateKey,
  type AnswerInput, type ReviewRequest, type ReviewState,
} from "./review-requests";

/**
 * Review requests through the site's own authenticated API (user pool; editors and admins). The condition `state = open`
 * on every change means two people answering at once, or an answer racing the deadline, cannot both win.
 */

const FIELDS = "id subject mode reason ask raisedBy raisedAt deadline state reviewStateKey dueAt answer links history appliedIn updatedAt";
/** How many pages of 500 the page reads of each decided state, most recently decided first. Every open request is read. */
const MAX_DECIDED_PAGES = 10;
const STATE_QUERY = `query ReviewsInState($reviewStateKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) { listReviewRequestsByReviewStateKeyAndUpdatedAt(reviewStateKey: $reviewStateKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) { items { ${FIELDS} } nextToken } }`;

type GraphQLResult = { data?: Record<string, any>; errors?: { message?: string; errorType?: string }[] };

async function run(query: string, variables: Record<string, unknown>): Promise<GraphQLResult> {
  const client = generateClient({ authMode: "userPool" });
  try {
    return (await client.graphql({ query, variables })) as GraphQLResult;
  } catch (error) {
    // Amplify throws the response when AppSync returns errors.
    return (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
}

export type ReviewLoad = { state: "ready"; requests: ReviewRequest[]; readIds: string[]; userKey: string } | { state: "forbidden" } | { state: "unavailable" };

export async function currentUserKey(): Promise<string> {
  return (await getCurrentUser()).userId;
}

type StateRead = { state: "ready"; rows: Record<string, unknown>[] } | { state: "forbidden" } | { state: "unavailable" };

/** The requests in one state, from that state's partition of the state index, most recently changed first; `maxPages` pages of 500 at most, or all of them. */
async function readState(state: ReviewState, maxPages: number | null): Promise<StateRead> {
  const rows: Record<string, unknown>[] = [];
  let nextToken: string | null = null;
  for (let page = 0; maxPages === null || page < maxPages; page += 1) {
    const result = await run(STATE_QUERY, { reviewStateKey: reviewStateKey(state), sortDirection: "DESC", limit: 500, nextToken });
    if (result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) return { state: "forbidden" };
    const connection = result.data?.listReviewRequestsByReviewStateKeyAndUpdatedAt;
    if (result.errors?.length || !connection) return { state: "unavailable" };
    rows.push(...connection.items.filter(Boolean));
    nextToken = connection.nextToken ?? null;
    if (!nextToken) break;
  }
  return { state: "ready", rows };
}

/**
 * Loads the requests by index: every open request, and the decided ones (answered, timed out, withdrawn) most recently decided first. Nothing lists the table,
 * and nothing is timed out here: a soft review's deadline is a timer on the server, so the state read is the state.
 */
export async function loadReviews(): Promise<ReviewLoad> {
  let userKey: string;
  try {
    userKey = await currentUserKey();
  } catch {
    return { state: "unavailable" };
  }
  const reads = await Promise.all([readState("open", null), ...DECIDED_STATES.map((state) => readState(state, MAX_DECIDED_PAGES))]);
  const refused = reads.find((read) => read.state !== "ready");
  if (refused) return refused.state === "forbidden" ? { state: "forbidden" } : { state: "unavailable" };
  const requests = reads.flatMap((read) => (read.state === "ready" ? read.rows : [])).map(normalizeReviewRow);
  const marks = await run(
    `query Marks($filter: ModelReviewReadMarkFilterInput, $limit: Int) { listReviewReadMarks(filter: $filter, limit: $limit) { items { requestId } } }`,
    { filter: { userKey: { eq: userKey } }, limit: 5000 },
  );
  const readIds = (marks.data?.listReviewReadMarks?.items ?? []).filter(Boolean).map((mark: { requestId: string }) => mark.requestId);
  return { state: "ready", requests, readIds, userKey };
}

/** Records an answer. Throws an Error with a sentence for the page when the request is closed or the write loses a race. */
export async function answerReviewRequest(request: ReviewRequest, input: AnswerInput, by: string, now: Date = new Date()): Promise<ReviewRequest> {
  const update = answerUpdate(request, input, by, now);
  const result = await run(
    `mutation Answer($input: UpdateReviewRequestInput!, $condition: ModelReviewRequestConditionInput) { updateReviewRequest(input: $input, condition: $condition) { ${FIELDS} } }`,
    { input: update, condition: { state: { eq: "open" } } },
  );
  if (result.errors?.some((entry) => /conditional/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) {
    throw new Error("Someone else answered this, or it proceeded at its deadline. Refresh to see the result.");
  }
  if (result.errors?.length || !result.data?.updateReviewRequest) throw new Error("Could not save the answer. Nothing was changed.");
  return normalizeReviewRow(result.data.updateReviewRequest);
}

/** This user has seen the request. Create the mark; if it exists, refresh it. */
export async function markReviewRead(userKey: string, requestId: string, now: Date = new Date()): Promise<void> {
  const input = { id: `${userKey}#${requestId}`, requestId, userKey, readAt: now.toISOString() };
  const created = await run(
    `mutation Mark($input: CreateReviewReadMarkInput!) { createReviewReadMark(input: $input) { id } }`, { input });
  if (created.errors?.length) {
    await run(`mutation Mark($input: UpdateReviewReadMarkInput!) { updateReviewReadMark(input: $input) { id } }`, { input });
  }
}

const LOOKUPS_AT_A_TIME = 8;
/** The opening of a story, for a reviewer who has not opened it: the deck, then the first paragraphs of the body. */
const EXCERPT_CHARACTERS = 900;

export function storyExcerpt(deck: string | null | undefined, body: readonly (string | null)[] | null | undefined): string | null {
  const text = [deck, ...(body ?? [])].map((part) => (part ?? "").trim()).filter(Boolean).join("\n\n");
  if (!text) return null;
  if (text.length <= EXCERPT_CHARACTERS) return text;
  const cut = text.slice(0, EXCERPT_CHARACTERS);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), EXCERPT_CHARACTERS - 80))}…`;
}

/**
 * Titles of the stories that review requests are about (and of the ideas a batch names), by lineage id, their current stage, and the ids of stories
 * that no longer exist (no version of the lineage remains). A story that cannot be read simply has no entry (the card falls back to the id).
 * One read per story, a few at a time: a batch can name any number of ideas.
 */
export async function loadStoryTitles(ids: string[]): Promise<{ titles: Record<string, string>; deleted: string[]; excerpts?: Record<string, string>; stages?: Record<string, string>; itemIds?: Record<string, string> }> {
  const titles: Record<string, string> = {};
  const itemIds: Record<string, string> = {};
  const excerpts: Record<string, string> = {};
  const stages: Record<string, string> = {};
  const deleted: string[] = [];
  const unique = [...new Set(ids)];
  for (let start = 0; start < unique.length; start += LOOKUPS_AT_A_TIME) await Promise.all(unique.slice(start, start + LOOKUPS_AT_A_TIME).map(async (id) => {
    const result = await run(
      `query StoryTitle($lineageId: ID!) { listItemsByLineageAndVersion(lineageId: $lineageId, limit: 50) { items { id versionNumber headline title deck body stage } } }`,
      { lineageId: id },
    );
    // Only a clean, empty answer means the story is gone; a failed lookup says nothing.
    if (!result.errors?.length && result.data?.listItemsByLineageAndVersion && !(result.data.listItemsByLineageAndVersion.items ?? []).filter(Boolean).length) deleted.push(id);
    const items = (result.data?.listItemsByLineageAndVersion?.items ?? []).filter(Boolean) as { id?: string; versionNumber?: number; headline?: string; title?: string; deck?: string | null; body?: (string | null)[] | null; stage?: string | null }[];
    const newest = items.sort((a, b) => (b.versionNumber ?? 0) - (a.versionNumber ?? 0))[0];
    const title = newest?.headline || newest?.title;
    if (title) titles[id] = title;
    const excerpt = storyExcerpt(newest?.deck, newest?.body);
    if (excerpt) excerpts[id] = excerpt;
    if (newest?.stage) stages[id] = newest.stage;
    if (newest?.id) itemIds[id] = newest.id;   // any record of the lineage: setItemStars rates the lineage's working record
  }));
  return { titles, deleted, excerpts, stages, itemIds };
}

/**
 * Saves a row of the rating agent's daily review (`ratingRowUpdate`, `ratingDismissUpdate`). The condition is that the request is still open and
 * unchanged since it was read, so a second answer, or the agent adding Stories meanwhile, is never overwritten.
 */
export async function saveRatingReview(request: ReviewRequest, update: Record<string, unknown>): Promise<ReviewRequest> {
  const result = await run(
    `mutation RatingRow($input: UpdateReviewRequestInput!, $condition: ModelReviewRequestConditionInput) { updateReviewRequest(input: $input, condition: $condition) { ${FIELDS} } }`,
    { input: update, condition: { and: [{ state: { eq: "open" } }, { updatedAt: { eq: request.updatedAt } }] } },
  );
  if (result.errors?.some((entry) => /conditional/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) {
    throw new Error("This review changed since you opened it. Refresh, then answer again.");
  }
  if (result.errors?.length || !result.data?.updateReviewRequest) throw new Error("Your answer could not be saved. Nothing was changed on the review.");
  return normalizeReviewRow(result.data.updateReviewRequest);
}

/**
 * Changes only the note of an answered request (see `answerReasonUpdate`). The condition is that the
 * request is still in the state it was read in, so a change cannot overwrite a request that closed or timed out meanwhile.
 */
export async function saveReviewReason(request: ReviewRequest, update: Record<string, unknown>): Promise<ReviewRequest> {
  const result = await run(
    `mutation Reason($input: UpdateReviewRequestInput!, $condition: ModelReviewRequestConditionInput) { updateReviewRequest(input: $input, condition: $condition) { ${FIELDS} } }`,
    { input: update, condition: { state: { eq: request.state } } },
  );
  if (result.errors?.some((entry) => /conditional/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) {
    throw new Error("This request changed while you were writing. Your note is kept here; refresh, then save it again.");
  }
  if (result.errors?.length || !result.data?.updateReviewRequest) throw new Error("Your note could not be saved. It is kept here; keep typing or tap away to try again.");
  return normalizeReviewRow(result.data.updateReviewRequest);
}
