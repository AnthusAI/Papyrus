/**
 * How the Schedule page reads: one query per schedule state on the `scheduleState` + `scheduledPublishAt` index
 * (listItemsByScheduleStateAndScheduledPublishAt), each limited to the time range on screen by a key condition on the sort key. The index is sparse, so it holds
 * only versions that are or were scheduled, and nothing reads a table to show a few items. Pure, with the GraphQL call passed in, so the paging is tested against
 * synthetic rows (scripts/test-story-schedule.ts).
 */
import { isStoryItemType, storyItemTypeFilter, type ContentItemVersionRecord } from "./content-item-lifecycle";
import { SCHEDULE_ROW_FIELDS } from "./story-schedule";

/** The stored states, each one partition of the sparse index. Overdue is a scheduled or publishing row whose time has passed, so it is read with them. */
export const SCHEDULE_PAGE_STATES = ["scheduled", "publishing", "blocked"] as const;

export type ScheduleQueryFetch = (request: { query: string; field: string; variables: Record<string, unknown> }) => Promise<{ items: ContentItemVersionRecord[]; nextToken: string | null }>;

const FIELD = "listItemsByScheduleStateAndScheduledPublishAt";
const QUERY = `
  query ListItemsByScheduleStateAndScheduledPublishAt($scheduleState: String!, $scheduledPublishAt: ModelStringKeyConditionInput, $filter: ModelItemFilterInput, $limit: Int, $nextToken: String) {
    ${FIELD}(scheduleState: $scheduleState, scheduledPublishAt: $scheduledPublishAt, sortDirection: ASC, filter: $filter, limit: $limit, nextToken: $nextToken) {
      items { id lineageId versionNumber stage type status title headline slug section ${SCHEDULE_ROW_FIELDS} }
      nextToken
    }
  }
`;

/** Every Story version scheduled in [from, to] (UTC instants) in any of the page's states, earliest first. */
export async function readScheduledRange(fetch: ScheduleQueryFetch, from: string, to: string): Promise<ContentItemVersionRecord[]> {
  const perState = await Promise.all(SCHEDULE_PAGE_STATES.map(async scheduleState => {
    const rows: ContentItemVersionRecord[] = [];
    let nextToken: string | null = null;
    do {
      const page: { items: ContentItemVersionRecord[]; nextToken: string | null } = await fetch({
        query: QUERY, field: FIELD,
        variables: { scheduleState, scheduledPublishAt: { between: [from, to] }, filter: storyItemTypeFilter(), limit: 100, nextToken },
      });
      rows.push(...page.items);
      nextToken = page.nextToken;
    } while (nextToken);
    return rows;
  }));
  return perState.flat().sort((left, right) => String(left.scheduledPublishAt).localeCompare(String(right.scheduledPublishAt)) || left.id.localeCompare(right.id));
}

/** One published Story as the Schedule page shows it: the live version of a Story, with the moment it first went live. */
export type PublishedStoryRow = {
  /** The Item version that is live; it opens the Story in the editor. */
  id: string;
  lineageId: string;
  title: string;
  section: string | null;
  /** The UTC instant the Story was first published (`publishedAt` carries the first publication forward, so a republish does not move it). */
  publishedAt: string;
};

type PublishedItemRecord = { sourceItemId?: string | null; itemLineageId?: string | null; title?: string | null; headline?: string | null; slug?: string | null; section?: string | null; publishedAt?: string | null };
export type PublishedQueryFetch = (request: { query: string; field: string; variables: Record<string, unknown> }) => Promise<{ items: PublishedItemRecord[]; nextToken: string | null }>;

const PUBLISHED_FIELD = "listPublishedItemsByTypeStatusAndPublishedAt";
const PUBLISHED_QUERY = `
  query ListPublishedItemsByTypeStatusAndPublishedAt($typeStatus: String!, $publishedAt: ModelStringKeyConditionInput, $limit: Int, $nextToken: String) {
    ${PUBLISHED_FIELD}(typeStatus: $typeStatus, publishedAt: $publishedAt, sortDirection: ASC, limit: $limit, nextToken: $nextToken) {
      items { sourceItemId itemLineageId title headline slug section publishedAt }
      nextToken
    }
  }
`;

/**
 * Every Story first published in [from, to] (UTC instants), from the existing `typeStatus` + `publishedAt` index of PublishedItem: one key-conditioned query per
 * Story type of the site (`<type>#published`), so only the range on screen is read. Pages and the other system types are not Stories and are left out.
 */
export async function readPublishedRange(fetch: PublishedQueryFetch, types: readonly string[], from: string, to: string): Promise<PublishedStoryRow[]> {
  const perType = await Promise.all([...new Set(types)].filter(isStoryItemType).map(async type => {
    const rows: PublishedStoryRow[] = [];
    let nextToken: string | null = null;
    do {
      const page: { items: PublishedItemRecord[]; nextToken: string | null } = await fetch({
        query: PUBLISHED_QUERY, field: PUBLISHED_FIELD,
        variables: { typeStatus: `${type}#published`, publishedAt: { between: [from, to] }, limit: 100, nextToken },
      });
      for (const item of page.items) {
        if (!item.sourceItemId || !item.publishedAt) continue;
        rows.push({ id: item.sourceItemId, lineageId: item.itemLineageId ?? item.sourceItemId, title: item.headline || item.title || item.slug || "Untitled", section: item.section ?? null, publishedAt: item.publishedAt });
      }
      nextToken = page.nextToken;
    } while (nextToken);
    return rows;
  }));
  return perType.flat().sort((left, right) => left.publishedAt.localeCompare(right.publishedAt) || left.id.localeCompare(right.id));
}
