/**
 * Paging for a filtered DynamoDB index query. DynamoDB applies a `filter` after it reads `limit` rows, so a page can come
 * back with few matches, or none, and still carry a nextToken. A board column therefore keeps reading until it has a page's
 * worth of matches or the partition is exhausted, and never treats a short page as the end.
 */
export type FilteredPage<T> = { items: T[]; nextToken: string | null };

/** Rows read per request. The filter runs after this many rows are read, so a larger read finds sparse matches in fewer requests. */
export const STORY_STAGE_SCAN_PAGE_LIMIT = 100;

export async function collectFilteredPage<T>(
  fetchPage: (nextToken: string | null, scanLimit: number) => Promise<FilteredPage<T>>,
  options: { nextToken?: string | null; wanted: number; scanLimit?: number },
): Promise<FilteredPage<T>> {
  const scanLimit = options.scanLimit ?? STORY_STAGE_SCAN_PAGE_LIMIT;
  const items: T[] = [];
  let nextToken: string | null = options.nextToken ?? null;
  do {
    const page: FilteredPage<T> = await fetchPage(nextToken, scanLimit);
    items.push(...page.items);
    nextToken = page.nextToken;
  } while (nextToken && items.length < options.wanted);
  return { items, nextToken };
}
