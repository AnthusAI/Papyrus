/**
 * How a board column reads its stories: which index, which key, which filter. Pure, with the GraphQL call passed in, so the paging rules
 * can be tested against synthetic rows (scripts/test-board-head-index.ts).
 *
 * Two indexes can answer "the newest stories in stage X":
 * - `head`: listItemsByHeadStageAndUpdatedAt. Only the head row of a lineage carries `headStageKey` (lib/content-item-lifecycle.ts
 *   contentItemHeadStageKey), so a column reads one row per story and nothing is filtered away after the read.
 * - `stage`: listItemsByStageAndUpdatedAt. Every saved version keeps its stage, so the partition holds superseded rows too; the
 *   `versionState ne superseded` filter hides them only after DynamoDB has read them (about 4.7 rows read per story shown in Published on
 *   Machines on Machines). The fallback for a site whose backend has no head stage index, or whose index is not filled yet.
 */
import { boardStoryFilter, storyItemTypeFilter, type ContentItemVersionRecord } from "./content-item-lifecycle";
import { collectFilteredPage, type FilteredPage } from "./story-stage-paging";

export type StageIndexMode = "head" | "stage";

/** One GraphQL connection request. `field` is the query field the response carries. */
export type StageQueryFetch = (request: { query: string; field: string; variables: Record<string, unknown> }) => Promise<FilteredPage<ContentItemVersionRecord>>;

export const STORY_STAGE_PAGE_LIMIT = 25;

const STAGE_ROW_FIELDS = "id lineageId versionNumber stage type status title headline deck metadata slug section updatedAt versionCreatedBy starRating versionState";

const STAGE_INDEX = {
  head: { field: "listItemsByHeadStageAndUpdatedAt", key: "headStageKey", name: "ListItemsByHeadStageAndUpdatedAt" },
  stage: { field: "listItemsByStageAndUpdatedAt", key: "stage", name: "ListItemsByStageAndUpdatedAt" },
} as const;

function stageQuery(mode: StageIndexMode, withSince: boolean): { query: string; field: string } {
  const { field, key, name } = STAGE_INDEX[mode];
  const since = withSince ? ", $updatedAt: ModelStringKeyConditionInput" : "";
  const sinceArgument = withSince ? ", updatedAt: $updatedAt" : "";
  return {
    field,
    query: `
  query ${name}${withSince ? "Since" : ""}($key: String!${since}, $sortDirection: ModelSortDirection, $filter: ModelItemFilterInput, $limit: Int, $nextToken: String) {
    ${field}(${key}: $key${sinceArgument}, sortDirection: $sortDirection, filter: $filter, limit: $limit, nextToken: $nextToken) {
      items { ${STAGE_ROW_FIELDS} }
      nextToken
    }
  }
`,
  };
}

/** The filter each index needs. The head index holds no superseded row, so it needs only the story-type filter (a page or wiki row with a stage). */
export function stageQueryFilter(mode: StageIndexMode): Record<string, unknown> {
  return mode === "head" ? storyItemTypeFilter() : boardStoryFilter();
}

/** The partition key value for a stage. A dedicated stack stores the bare stage; a shared stack's head key is tenant-prefixed, which the console does not read yet. */
export function stageQueryKey(_mode: StageIndexMode, stage: string): string {
  return stage;
}

/** One newest-updated-first page of the stories in one stage. Keeps reading while the filter leaves the page short, and never treats a short page as the end. */
export async function readStoryStagePage(
  fetch: StageQueryFetch,
  mode: StageIndexMode,
  stage: string,
  options: { nextToken?: string | null; limit?: number; scanLimit?: number } = {},
): Promise<FilteredPage<ContentItemVersionRecord>> {
  const limit = options.limit ?? STORY_STAGE_PAGE_LIMIT;
  const { query, field } = stageQuery(mode, false);
  return collectFilteredPage<ContentItemVersionRecord>((token, scanLimit) => fetch({
    query,
    field,
    // The head index has nothing to filter away but the rare non-story row, so it asks for exactly a page.
    variables: { key: stageQueryKey(mode, stage), sortDirection: "DESC", filter: stageQueryFilter(mode), limit: mode === "head" ? limit : Math.max(limit, scanLimit), nextToken: token },
  }), { nextToken: options.nextToken ?? null, wanted: limit, scanLimit: options.scanLimit });
}

/**
 * Every story in one stage whose `updatedAt` is at or after `since`, newest first: a key condition on the index's sort key, so a quiet stage
 * costs one request that returns nothing. On the head index a changed story is its new head row only.
 */
export async function readStoryStageChangesSince(
  fetch: StageQueryFetch,
  mode: StageIndexMode,
  stage: string,
  since: string,
): Promise<ContentItemVersionRecord[]> {
  const { query, field } = stageQuery(mode, true);
  const changed: ContentItemVersionRecord[] = [];
  let nextToken: string | null = null;
  do {
    const page: FilteredPage<ContentItemVersionRecord> = await fetch({
      query,
      field,
      variables: { key: stageQueryKey(mode, stage), updatedAt: { ge: since }, sortDirection: "DESC", filter: stageQueryFilter(mode), limit: STORY_STAGE_PAGE_LIMIT, nextToken },
    });
    changed.push(...page.items);
    nextToken = page.nextToken;
  } while (nextToken);
  return changed;
}

/** Whether a GraphQL error says the backend has no head stage index (a site whose data deploy predates it): the board then reads the stage index. */
export function isMissingHeadStageIndexError(reason: unknown): boolean {
  const message = reason instanceof Error ? reason.message : String(reason ?? "");
  return /listItemsByHeadStageAndUpdatedAt|headStageKey/.test(message) && /(FieldUndefined|undefined|Unknown|not defined|Validation)/i.test(message);
}
