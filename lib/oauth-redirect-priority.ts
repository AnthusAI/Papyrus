function originOf(value: string): string {
  const trimmed = value.replace(/\/+$/, "");
  try {
    const parsed = new URL(trimmed);
    const hostname = parsed.hostname === "127.0.0.1" || parsed.hostname === "::1" ? "localhost" : parsed.hostname;
    return `${parsed.protocol}//${hostname}${parsed.port ? `:${parsed.port}` : ""}`;
  } catch {
    return trimmed;
  }
}

function pathOf(value: string): string | null {
  try {
    return new URL(value).pathname.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

/**
 * Puts the redirect URLs of the current origin first; among those, the
 * newsroom return path leads when the site has one, so Amplify (which signs in
 * with the first entry) returns an editor to the newsroom.
 */
export function prioritizeRedirectUrlsForOrigin(
  urls: readonly string[],
  currentOrigin: string,
  publicNewsroomBasePath: string,
): string[] {
  const origin = originOf(currentOrigin);
  const newsroomPath = publicNewsroomBasePath.replace(/\/+$/, "");
  const head = urls.filter((value) => originOf(value) === origin);
  if (head.length === 0) return [...urls];
  const tail = urls.filter((value) => originOf(value) !== origin);
  const newsroomFirst =
    newsroomPath === ""
      ? head
      : [...head.filter((value) => pathOf(value) === newsroomPath), ...head.filter((value) => pathOf(value) !== newsroomPath)];
  return [...newsroomFirst, ...tail];
}
