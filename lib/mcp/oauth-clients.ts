/** Only explicitly registered public clients and exact safe redirect URIs are accepted. */
export function safeMcpRedirect(value: string): boolean {
  try {
    const url = new URL(value);
    // URL accepts host characters such as semicolons that are not safe in a CSP host-source.
    if (url.hostname !== "[::1]" && !/^[a-z0-9.-]+$/.test(url.hostname)) return false;
    return !url.username && !url.password && !url.hash && (url.protocol === "https:" || (url.protocol === "http:" && ["127.0.0.1", "[::1]", "localhost"].includes(url.hostname)));
  } catch { return false; }
}

export function mcpOAuthClients(env: Record<string, string | undefined> = process.env): Record<string, string[]> | null {
  try {
    const value: unknown = JSON.parse(env.PAPYRUS_MCP_OAUTH_CLIENTS ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const entries = Object.entries(value);
    if (!entries.length || entries.some(([key, urls]) => !key || !Array.isArray(urls) || !urls.length || urls.some(url => typeof url !== "string" || !safeMcpRedirect(url)))) return null;
    return Object.fromEntries(entries) as Record<string, string[]>;
  } catch { return null; }
}
