export type VideoMode = "preview" | "mp4";

function parseVideoMode(value: string | null | undefined): VideoMode | null {
  if (value === "preview" || value === "mp4") return value;
  return null;
}

/** Server-safe mode from env only. Production always returns `"mp4"`. */
export function resolveVideoModeFromEnv(): VideoMode {
  if (process.env.NODE_ENV === "production") return "mp4";
  return parseVideoMode(process.env.NEXT_PUBLIC_PAPYRUS_VIDEO_MODE) ?? "preview";
}

/** Client-only `?video=` override. Returns null when absent or in production. */
export function resolveVideoModeFromSearch(search: string): VideoMode | null {
  if (process.env.NODE_ENV === "production") return null;
  const query = search.startsWith("?") ? search.slice(1) : search;
  return parseVideoMode(new URLSearchParams(query).get("video"));
}

/**
 * Effective video mode for the reader.
 * Production always uses `"mp4"`. In development, `?video=` overrides
 * `NEXT_PUBLIC_PAPYRUS_VIDEO_MODE` (default `"preview"`).
 */
export function resolveVideoMode(): VideoMode {
  if (process.env.NODE_ENV === "production") return "mp4";
  if (typeof window !== "undefined") {
    const fromSearch = resolveVideoModeFromSearch(window.location.search);
    if (fromSearch) return fromSearch;
  }
  return resolveVideoModeFromEnv();
}

/**
 * Server-safe gate for fetching VideoML DSL scripts.
 * Always true in development so `?video=preview` and `?video=mp4` can both
 * work without restarting the server. Production never fetches scripts.
 */
export function shouldFetchVideoScripts(): boolean {
  return process.env.NODE_ENV === "development";
}
