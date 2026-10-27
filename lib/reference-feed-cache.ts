/**
 * Stale-while-revalidate copies of what the editor last saw, so a return visit paints cards (and the signed-in name) at once
 * while the real reads run in the background. Display state only: the backend still authorizes every call, a cached copy never
 * enables an action by itself, and everything here is dropped on sign-out. Every storage touch is guarded: the page renders
 * the same, only slower, when storage is blocked or full.
 */
import type { ReferenceRecord } from "./category-repository";
import type { RelevanceDecisionView } from "./relevance-decisions";
import type { ReferencePreview } from "./reference-preview";

const FEED_PREFIX = "papyrus.references.feed.v1.";
const SESSION_PREFIX = "papyrus.newsroom.session.v1.";
/** A saved session summary is trusted for display only this long; the live check always still runs. */
export const SESSION_DISPLAY_TTL_MS = 15 * 60 * 1000;

export type FeedSnapshot = {
  savedAt: number;
  references: ReferenceRecord[];
  previews: Array<[string, ReferencePreview]>;
  decisions: Array<[string, RelevanceDecisionView]>;
};

export type SessionDisplay = {
  savedAt: number;
  label: string;
  isAdmin: boolean;
};

function storageOf(kind: "local" | "session"): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function read<T>(kind: "local" | "session", key: string): T | null {
  try {
    const raw = storageOf(kind)?.getItem(key);
    return raw ? JSON.parse(raw) as T : null;
  } catch {
    return null;
  }
}

function write(kind: "local" | "session", key: string, value: unknown): boolean {
  try {
    const storage = storageOf(kind);
    if (!storage) return false;
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function remove(kind: "local" | "session", key: string) {
  try { storageOf(kind)?.removeItem(key); } catch { /* nothing to clear */ }
}

/** The fields a card needs, and nothing else: a smaller copy that fits, and less private text at rest. */
export function slimReference(reference: ReferenceRecord): ReferenceRecord {
  return {
    id: reference.id,
    lineageId: reference.lineageId,
    versionNumber: reference.versionNumber,
    versionState: reference.versionState,
    corpusId: reference.corpusId,
    externalItemId: reference.externalItemId,
    title: reference.title,
    sourceUri: reference.sourceUri,
    mediaType: reference.mediaType,
    sourcePublishedAt: reference.sourcePublishedAt,
    retrievedAt: reference.retrievedAt,
    importedAt: reference.importedAt,
    createdAt: reference.createdAt,
    curationStatus: reference.curationStatus,
    curationStatusUpdatedAt: reference.curationStatusUpdatedAt,
    curationStatusReason: reference.curationStatusReason,
  };
}

export function feedCacheKey(siteId: string): string {
  return `${FEED_PREFIX}${siteId}`;
}

export function loadFeedSnapshot(siteId: string): FeedSnapshot | null {
  const snapshot = read<FeedSnapshot>("local", feedCacheKey(siteId));
  if (!snapshot || !Array.isArray(snapshot.references) || !snapshot.references.length) return null;
  return snapshot;
}

/** Saves the newest copy. On a full store it keeps the newest half, then gives up quietly. */
export function saveFeedSnapshot(
  siteId: string,
  parts: { references: ReferenceRecord[]; previews: ReadonlyMap<string, ReferencePreview>; decisions: ReadonlyMap<string, RelevanceDecisionView> },
  now = Date.now(),
): boolean {
  let references = parts.references.map(slimReference);
  for (let attempt = 0; attempt < 4 && references.length; attempt += 1) {
    const kept = new Set(references.map((reference) => reference.lineageId ?? reference.id));
    const snapshot: FeedSnapshot = {
      savedAt: now,
      references,
      previews: [...parts.previews].filter(([lineage]) => kept.has(lineage)),
      decisions: [...parts.decisions].filter(([lineage]) => kept.has(lineage)).map(([lineage, decision]) => [lineage, { ...decision, provenance: null }]),
    };
    if (write("local", feedCacheKey(siteId), snapshot)) return true;
    references = references.slice(0, Math.ceil(references.length / 2));
  }
  return false;
}

export function clearFeedSnapshot(siteId: string) {
  remove("local", feedCacheKey(siteId));
}

export function loadSessionDisplay(siteId: string, now = Date.now()): SessionDisplay | null {
  const saved = read<SessionDisplay>("session", `${SESSION_PREFIX}${siteId}`);
  if (!saved || typeof saved.label !== "string" || typeof saved.savedAt !== "number") return null;
  return now - saved.savedAt <= SESSION_DISPLAY_TTL_MS ? saved : null;
}

export function saveSessionDisplay(siteId: string, display: Omit<SessionDisplay, "savedAt">, now = Date.now()) {
  write("session", `${SESSION_PREFIX}${siteId}`, { ...display, savedAt: now });
}

/** Sign-out: nothing of the signed-in view survives in this browser. */
export function clearSavedNewsroomDisplay(siteId: string) {
  remove("session", `${SESSION_PREFIX}${siteId}`);
  clearFeedSnapshot(siteId);
}
