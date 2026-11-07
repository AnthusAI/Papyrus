import type { ContentItemVersionRecord } from "./content-item-lifecycle";

/** How often a visible board asks for changes. Reloading the page, returning to the tab and the user's own edits refresh sooner. */
export const BOARD_REFRESH_INTERVAL_MILLISECONDS = 5 * 60_000;
/** Returning to the tab or focusing the window refreshes only if the last refresh is at least this old, so quick tab switching costs nothing. */
export const BOARD_REFRESH_MINIMUM_GAP_MILLISECONDS = 60_000;

type VisibilitySource = Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
type FocusSource = Pick<Window, "addEventListener" | "removeEventListener">;

export type BoardRefreshOptions = {
  refresh: () => Promise<unknown>;
  intervalMilliseconds?: number;
  minimumGapMilliseconds?: number;
  now?: () => number;
  visibility?: VisibilitySource;
  focus?: FocusSource;
  setTimer?: (callback: () => void, milliseconds: number) => unknown;
  clearTimer?: (timer: unknown) => void;
};

export type BoardRefreshController = {
  /** Refresh now, for the user's own action; never rate limited. A refresh already running is followed by one more. */
  refreshNow: () => void;
  stop: () => void;
};

/**
 * One timer for the whole board, running only while the tab is visible. Becoming visible again or regaining focus refreshes
 * when the last refresh is older than the minimum gap. The caller does the first load itself; this starts counting from now.
 */
export function startBoardRefresh(options: BoardRefreshOptions): BoardRefreshController {
  const interval = options.intervalMilliseconds ?? BOARD_REFRESH_INTERVAL_MILLISECONDS;
  const minimumGap = options.minimumGapMilliseconds ?? BOARD_REFRESH_MINIMUM_GAP_MILLISECONDS;
  const now = options.now ?? Date.now;
  const visibility = options.visibility ?? document;
  const focus = options.focus ?? window;
  const setTimer = options.setTimer ?? ((callback, milliseconds) => window.setInterval(callback, milliseconds));
  const clearTimer = options.clearTimer ?? ((timer) => window.clearInterval(timer as number));
  let timer: unknown = null;
  let lastRefreshAt = now();
  let running = false;
  let again = false;
  let stopped = false;

  const run = () => {
    if (stopped) return;
    if (running) { again = true; return; }
    running = true;
    lastRefreshAt = now();
    void Promise.resolve().then(options.refresh).catch(() => undefined).finally(() => {
      running = false;
      if (again) { again = false; run(); }
    });
  };
  const arm = () => { if (timer === null) timer = setTimer(() => { if (visibility.visibilityState === "visible") run(); }, interval); };
  const disarm = () => { if (timer !== null) { clearTimer(timer); timer = null; } };
  const refreshIfStale = () => { if (now() - lastRefreshAt >= minimumGap) run(); };
  const onVisibilityChange = () => {
    if (visibility.visibilityState === "visible") { disarm(); arm(); refreshIfStale(); } else disarm();
  };
  const onFocus = () => { if (visibility.visibilityState === "visible") refreshIfStale(); };

  if (visibility.visibilityState === "visible") arm();
  visibility.addEventListener("visibilitychange", onVisibilityChange);
  focus.addEventListener("focus", onFocus);
  return {
    refreshNow: run,
    stop: () => {
      stopped = true;
      disarm();
      visibility.removeEventListener("visibilitychange", onVisibilityChange);
      focus.removeEventListener("focus", onFocus);
    },
  };
}

export type VersionBucket = { versions: ContentItemVersionRecord[]; nextToken: string | null; pagesLoaded: number };

/** The newest `updatedAt` among a stage's rows: the "changed since" place for that stage. Timestamps are ISO strings, so they compare as text. */
export function newestUpdatedAt(versions: readonly ContentItemVersionRecord[]): string | null {
  let newest: string | null = null;
  for (const version of versions) if (version.updatedAt && (newest === null || version.updatedAt > newest)) newest = version.updatedAt;
  return newest;
}

/**
 * Merge rows that changed since the last refresh into the stage buckets. A changed row replaces the copy with the same id, and also
 * leaves any other stage's bucket that still holds it (its stage changed). Pages already loaded, and their tokens, are kept.
 * A row that was deleted cannot be seen this way; a reload shows it gone.
 */
export function applyChangedVersions(
  buckets: Record<string, VersionBucket>,
  changedByStage: Record<string, ContentItemVersionRecord[]>,
): Record<string, VersionBucket> {
  const changedIds = new Set(Object.values(changedByStage).flatMap(rows => rows.map(row => row.id)));
  if (!changedIds.size) return buckets;
  const next: Record<string, VersionBucket> = {};
  for (const [stageKey, bucket] of Object.entries(buckets)) {
    next[stageKey] = bucket.versions.some(version => changedIds.has(version.id))
      ? { ...bucket, versions: bucket.versions.filter(version => !changedIds.has(version.id)) } : bucket;
  }
  for (const [stageKey, rows] of Object.entries(changedByStage)) {
    if (!rows.length) continue;
    const existing = next[stageKey];
    const sorted = [...rows].sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
    next[stageKey] = { versions: [...sorted, ...(existing?.versions ?? [])], nextToken: existing?.nextToken ?? null, pagesLoaded: existing?.pagesLoaded ?? 1 };
  }
  return next;
}
