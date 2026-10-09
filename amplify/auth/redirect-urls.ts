export const DEFAULT_NEWSROOM_BASE_PATH = "/newsroom";

type ParsedRedirectUrl = { original: string; origin: string; path: string } | null;

function parseRedirectUrl(value: string): ParsedRedirectUrl {
  try {
    const parsed = new URL(value);
    return { original: value, origin: parsed.origin, path: parsed.pathname.replace(/\/+$/, "") };
  } catch {
    return null;
  }
}

/**
 * Expands every origin in an OAuth redirect list to both the newsroom return
 * path and the site root, newsroom first. Amplify signs in with the first
 * entry that matches the current origin, so a list that names only
 * `https://host/` would land a signed-in editor on the public reader.
 *
 * With `newsroomBasePath` of `""` (a CMS-only host that mounts the newsroom at
 * `/`), the root already is the newsroom and nothing is added. Explicit
 * entries are kept; unparseable entries pass through unchanged.
 */
export function expandNewsroomRedirectUrls(
  redirectUrls: readonly string[],
  newsroomBasePath: string = DEFAULT_NEWSROOM_BASE_PATH,
): string[] {
  const newsroomPath = newsroomBasePath.replace(/\/+$/, "");
  const originOrder: string[] = [];
  const explicitByOrigin = new Map<string, string[]>();
  const passthrough: string[] = [];

  for (const value of redirectUrls) {
    const parsed = parseRedirectUrl(value);
    if (!parsed) {
      passthrough.push(value);
      continue;
    }
    if (!explicitByOrigin.has(parsed.origin)) {
      originOrder.push(parsed.origin);
      explicitByOrigin.set(parsed.origin, []);
    }
    explicitByOrigin.get(parsed.origin)?.push(value);
  }

  const expanded: string[] = [];
  for (const origin of originOrder) {
    const explicit = explicitByOrigin.get(origin) ?? [];
    if (newsroomPath === "") {
      expanded.push(...explicit);
      continue;
    }
    const newsroomEntries = explicit.filter((value) => parseRedirectUrl(value)?.path === newsroomPath);
    const otherEntries = explicit.filter((value) => {
      const path = parseRedirectUrl(value)?.path;
      return path !== newsroomPath && path !== "";
    });
    expanded.push(
      ...(newsroomEntries.length > 0 ? newsroomEntries : [`${origin}${newsroomPath}`]),
      `${origin}/`,
      ...otherEntries,
    );
  }
  expanded.push(...passthrough);
  return [...new Set(expanded)];
}
