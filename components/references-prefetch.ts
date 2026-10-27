/**
 * Starts the References reads as soon as the editor session is confirmed, in parallel with the summary dashboard, instead of after it.
 * The page that needs them takes the in-flight request once; anything later, or a retry, makes a fresh read. This is a head start
 * on the same reads, not a cache: the backend authorizes each call exactly as before.
 */
import {
  loadEditorMessagesData,
  loadEditorReferencesData,
  loadEditorSemanticRelationsData,
} from "./news-desk-taxonomy-client";

const HEAD_START_MS = 60_000;
type Started = { startedAt: number; promise: Promise<unknown> };
const started = new Map<string, Started>();

const LOADERS = {
  references: loadEditorReferencesData,
  relations: loadEditorSemanticRelationsData,
  messages: loadEditorMessagesData,
} as const;
type Key = keyof typeof LOADERS;

/** Begin all three reads. Safe to call twice; a failure is reported to whoever takes the read, never as an unhandled rejection. */
export function prefetchReferencesFeed(now = Date.now()) {
  for (const key of Object.keys(LOADERS) as Key[]) {
    if (started.has(key)) continue;
    const promise = LOADERS[key]();
    promise.catch(() => undefined);
    started.set(key, { startedAt: now, promise });
  }
}

function take<Key2 extends Key>(key: Key2, now = Date.now()): ReturnType<(typeof LOADERS)[Key2]> {
  const head = started.get(key);
  started.delete(key);
  if (head && now - head.startedAt <= HEAD_START_MS) return head.promise as ReturnType<(typeof LOADERS)[Key2]>;
  return LOADERS[key]() as ReturnType<(typeof LOADERS)[Key2]>;
}

export const loadReferencesWithHeadStart = () => take("references");
export const loadRelationsWithHeadStart = () => take("relations");
export const loadMessagesWithHeadStart = () => take("messages");

/** Forget any unclaimed head start (sign-out). */
export function discardReferencesHeadStart() {
  started.clear();
}
