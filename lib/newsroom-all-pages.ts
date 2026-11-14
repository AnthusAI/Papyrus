/** Every row a paged newsroom read returns, following `nextToken` to the end; rows repeated across pages are kept once. */
export async function loadAllPages<T extends { id?: string | null }>(
  loadPage: (nextToken: string | null) => Promise<{ items: T[]; nextToken?: string | null; hasMore: boolean }>,
): Promise<T[]> {
  const rows: T[] = [];
  const seenIds = new Set<string>();
  const seenTokens = new Set<string>();
  let nextToken: string | null = null;
  do {
    const page = await loadPage(nextToken);
    for (const row of page.items) {
      if (!row?.id || seenIds.has(row.id)) continue;
      seenIds.add(row.id);
      rows.push(row);
    }
    nextToken = page.hasMore ? page.nextToken ?? null : null;
    if (nextToken && seenTokens.has(nextToken)) throw new Error("The list repeated a page; reload to try again.");
    if (nextToken) seenTokens.add(nextToken);
  } while (nextToken);
  return rows;
}
