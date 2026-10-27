/** Merging loaded pages into the Monitoring lists. Kept free of other imports so the panel's tests can load it alone. */
import type {
  MonitoringCursors,
  MonitoringItem,
  MonitoringListName,
  MonitoringListRows,
  MonitoringOverview,
} from "./monitoring-overview";

/** Rows the editor has loaded beyond the first page of each list, and where each list continues. */
export type MonitoringLoadedPages = Partial<{ [L in MonitoringListName]: { rows: MonitoringListRows[L][]; cursor: string | null } }>;

const ROW_KEYS: { [L in MonitoringListName]: (row: MonitoringListRows[L]) => string } = {
  runs: (row) => `${row.runId}`,
  routerRuns: (row) => `${row.runId}`,
  items: (row) => `${row.monitorId ?? ""}|${row.sourceId}`,
  emailSubmissions: (row) => row.receiptId,
};

/**
 * The first page followed by loaded pages, with a row seen twice kept once. The refresh re-reads the first page, so
 * a row that moved onto it from a later page must not be listed again; for items the highest revision wins.
 */
export function mergeListPages<L extends MonitoringListName>(list: L, first: MonitoringListRows[L][], loaded: MonitoringListRows[L][]): MonitoringListRows[L][] {
  const keyOf = ROW_KEYS[list] as (row: MonitoringListRows[L]) => string;
  const seen = new Map<string, number>();
  const merged: MonitoringListRows[L][] = [];
  for (const row of [...first, ...loaded]) {
    const key = keyOf(row);
    const at = seen.get(key);
    if (at === undefined) {
      seen.set(key, merged.length);
      merged.push(row);
    } else if (list === "items" && (row as MonitoringItem).revision > (merged[at] as MonitoringItem).revision) {
      merged[at] = row;
    }
  }
  return merged;
}

/**
 * What the page shows: the refreshed first page of every list plus whatever the editor loaded, with each list's
 * cursor. With `held` the email list is replaced by the held-for-review list (its own pages).
 */
export function withLoadedPages(overview: MonitoringOverview, loaded: MonitoringLoadedPages, held: MonitoringLoadedPages["emailSubmissions"] | null): MonitoringOverview {
  const cursors: MonitoringCursors = {};
  const lists: Partial<Record<MonitoringListName, unknown[]>> = {};
  for (const list of ["runs", "routerRuns", "items", "emailSubmissions"] as const) {
    const extra = loaded[list];
    lists[list] = mergeListPages(list, (overview[list] ?? []) as never[], (extra?.rows ?? []) as never[]) as unknown[];
    cursors[list] = extra ? extra.cursor : overview.cursors?.[list] ?? null;
  }
  if (held) {
    lists.emailSubmissions = held.rows;
    cursors.emailSubmissions = held.cursor;
  }
  return { ...overview, ...(lists as Pick<MonitoringOverview, MonitoringListName>), cursors };
}
