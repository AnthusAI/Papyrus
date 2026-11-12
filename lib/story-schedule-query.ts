/**
 * How the Schedule page reads: one query per schedule state on the `scheduleState` + `scheduledPublishAt` index
 * (listItemsByScheduleStateAndScheduledPublishAt), each limited to the time range on screen by a key condition on the sort key. The index is sparse, so it holds
 * only versions that are or were scheduled, and nothing reads a table to show a few items. Pure, with the GraphQL call passed in, so the paging is tested against
 * synthetic rows (scripts/test-story-schedule.ts).
 */
import { storyItemTypeFilter, type ContentItemVersionRecord } from "./content-item-lifecycle";
import { SCHEDULE_ROW_FIELDS } from "./story-schedule";

/** The states the page shows. `cleared` rows are gone from the index's point of view: an editor cleared them. */
export const SCHEDULE_PAGE_STATES = ["scheduled", "overdue", "superseded", "published"] as const;

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
