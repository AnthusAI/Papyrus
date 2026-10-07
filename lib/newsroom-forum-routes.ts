import { toPublicNewsroomPath } from "./newsroom-base-path";

export const FORUM_THREAD_ROUTE_PREFIX = "/newsroom/forum/";
export const INSIGHT_THREAD_ROUTE_PREFIX = "/newsroom/insights/";
export const FORUM_MESSAGE_HASH_PREFIX = "message-";

export function isForumThreadId(id: string | null | undefined): boolean {
  const value = String(id ?? "").trim();
  return value.startsWith("message-thread-");
}

export function isInsightThreadId(id: string | null | undefined): boolean {
  const value = String(id ?? "").trim();
  return Boolean(value) && !isForumThreadId(value);
}

export function getForumMessageAnchorId(messageId: string): string {
  return `${FORUM_MESSAGE_HASH_PREFIX}${encodeURIComponent(messageId.trim())}`;
}

export function parseForumMessageAnchorFromHash(hash: string | null | undefined): string | null {
  const raw = String(hash ?? "").replace(/^#/, "").trim();
  if (!raw.startsWith(FORUM_MESSAGE_HASH_PREFIX)) return null;
  const encoded = raw.slice(FORUM_MESSAGE_HASH_PREFIX.length);
  if (!encoded) return null;
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}

export type ParsedNewsroomForumRoute = {
  threadId: string | null;
  messageId: string | null;
  surface: "edition_forum" | "insight_forum" | null;
};

export function parseNewsroomForumRoute(pathname: string, hash?: string | null): ParsedNewsroomForumRoute {
  const segments = pathname.split("/").filter(Boolean);
  const newsroomIndex = segments.indexOf("newsroom");
  if (newsroomIndex < 0) {
    return { threadId: null, messageId: parseForumMessageAnchorFromHash(hash), surface: null };
  }
  const tail = segments.slice(newsroomIndex + 1);
  if (tail[0] === "insights" && tail[1]) {
    return {
      threadId: decodeURIComponent(tail[1]),
      messageId: parseForumMessageAnchorFromHash(hash),
      surface: "insight_forum",
    };
  }
  if (tail[0] === "forum" && tail[1]) {
    return {
      threadId: decodeURIComponent(tail[1]),
      messageId: parseForumMessageAnchorFromHash(hash),
      surface: "edition_forum",
    };
  }
  if (tail[0] === "messages" && tail[1] === "forum" && tail[2]) {
    return {
      threadId: decodeURIComponent(tail[2]),
      messageId: parseForumMessageAnchorFromHash(hash),
      surface: "edition_forum",
    };
  }
  if (tail[0] === "messages" && tail[1] && isForumThreadId(tail[1])) {
    return {
      threadId: decodeURIComponent(tail[1]),
      messageId: parseForumMessageAnchorFromHash(hash),
      surface: "edition_forum",
    };
  }
  return { threadId: null, messageId: parseForumMessageAnchorFromHash(hash), surface: null };
}

export function buildForumThreadUrl(
  threadId: string,
  options?: { messageId?: string | null; demo?: boolean },
): string {
  const encodedThreadId = encodeURIComponent(threadId.trim());
  const params = new URLSearchParams();
  if (options?.demo) params.set("demo", "1");
  const query = params.toString();
  const hash = options?.messageId ? getForumMessageAnchorId(options.messageId) : "";
  return toPublicNewsroomPath(`/newsroom/forum/${encodedThreadId}${query ? `?${query}` : ""}${hash ? `#${hash}` : ""}`);
}

export function buildInsightThreadUrl(
  threadId: string,
  options?: { messageId?: string | null; demo?: boolean },
): string {
  const encodedThreadId = encodeURIComponent(threadId.trim());
  const params = new URLSearchParams();
  if (options?.demo) params.set("demo", "1");
  const query = params.toString();
  const hash = options?.messageId ? getForumMessageAnchorId(options.messageId) : "";
  return toPublicNewsroomPath(`${INSIGHT_THREAD_ROUTE_PREFIX}${encodedThreadId}${query ? `?${query}` : ""}${hash ? `#${hash}` : ""}`);
}

export function buildThreadUrlForSurface(
  surface: ParsedNewsroomForumRoute["surface"],
  threadId: string,
  options?: { messageId?: string | null; demo?: boolean },
): string {
  if (surface === "insight_forum") return buildInsightThreadUrl(threadId, options);
  return buildForumThreadUrl(threadId, options);
}

export function readCurrentForumRoute(): ParsedNewsroomForumRoute {
  if (typeof window === "undefined") {
    return { threadId: null, messageId: null, surface: null };
  }
  return parseNewsroomForumRoute(window.location.pathname, window.location.hash);
}

export function pushForumThreadUrl(
  threadId: string | null,
  options?: { messageId?: string | null; demo?: boolean; replace?: boolean; surface?: ParsedNewsroomForumRoute["surface"] },
) {
  if (typeof window === "undefined") return;
  const surface = options?.surface ?? readCurrentForumRoute().surface;
  const url = threadId
    ? buildThreadUrlForSurface(surface, threadId, options)
    : (surface === "insight_forum" ? buildNewsroomInsightsIndexUrl(options?.demo) : buildNewsroomForumIndexUrl(options?.demo));
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (current === url) return;
  if (options?.replace) {
    window.history.replaceState(null, "", url);
  } else {
    window.history.pushState(null, "", url);
  }
}

export function pushInsightThreadUrl(
  threadId: string | null,
  options?: { messageId?: string | null; demo?: boolean; replace?: boolean },
) {
  pushForumThreadUrl(threadId, { ...options, surface: "insight_forum" });
}

export function buildNewsroomForumIndexUrl(demo?: boolean): string {
  const params = new URLSearchParams();
  if (demo) params.set("demo", "1");
  const query = params.toString();
  return toPublicNewsroomPath(query ? `/newsroom?${query}` : "/newsroom");
}

export function buildNewsroomInsightsIndexUrl(demo?: boolean, domain?: string): string {
  const params = new URLSearchParams();
  if (demo) params.set("demo", "1");
  if (domain?.trim()) params.set("domain", domain.trim());
  const query = params.toString();
  return toPublicNewsroomPath(query ? `/newsroom/insights?${query}` : "/newsroom/insights");
}
