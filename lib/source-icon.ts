import { fetchPublic } from "./source-frameable";

/**
 * A source's own icon, fetched on the server. Guessing `/favicon.ico` from the browser fails often: some sites serve a fully
 * transparent placeholder there, and others refuse requests from another site. The page's own `<link rel="icon">` tags name
 * the icon the site actually uses, so the newsroom reads those first and passes the image through.
 */

const MAX_HTML_BYTES = 256 * 1024;
const MAX_ICON_BYTES = 256 * 1024;
/** A bare 16x16 ICO is about 200 bytes; at that size it is often an empty placeholder, so the guessed path must beat it. */
const MIN_GUESSED_ICON_BYTES = 300;

export type SourceIcon = { body: ArrayBuffer; contentType: string };

/** A bare host name such as `www.brookings.edu`: letters, digits, hyphens and dots only. */
export function isHostName(host: string): boolean {
  return host.length <= 253 && /^(?=.*[a-z])[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(host);
}

function attribute(tag: string, name: string): string | null {
  const match = tag.match(new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i"));
  return match ? (match[1] ?? match[2] ?? match[3] ?? "") : null;
}

/** The icons a page declares, best first: touch icons, then the largest declared size. Mask icons are single-colour stencils and are skipped. */
export function iconCandidates(html: string, base: string): string[] {
  const found: { href: string; score: number }[] = [];
  for (const tag of html.match(/<link\b[^>]*>/gi) ?? []) {
    const rel = (attribute(tag, "rel") ?? "").toLowerCase().split(/\s+/);
    if (!rel.some((word) => word === "icon" || word === "apple-touch-icon" || word === "apple-touch-icon-precomposed")) continue;
    const href = attribute(tag, "href");
    if (!href) continue;
    let absolute: string;
    try { absolute = new URL(href, base).toString(); } catch { continue; }
    const size = Math.max(0, ...(attribute(tag, "sizes") ?? "").split(/\s+/).map((s) => Number.parseInt(s, 10)).filter(Number.isFinite));
    const touch = rel.some((word) => word.startsWith("apple-touch-icon"));
    found.push({ href: absolute, score: (touch ? 10_000 : 0) + (size || (touch ? 180 : 16)) });
  }
  return [...new Set(found.sort((a, b) => b.score - a.score).map(({ href }) => href))];
}

async function readLimited(response: Response, limit: number): Promise<ArrayBuffer | null> {
  const declared = Number(response.headers.get("content-length"));
  if (declared > limit) { void response.body?.cancel(); return null; }
  const body = await response.arrayBuffer().catch(() => null);
  return body && body.byteLength <= limit ? body : null;
}

/** The first `limit` bytes of a page: icons are declared in its head, and some home pages run to a megabyte. */
async function readPrefix(response: Response, limit: number): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (total < limit) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.byteLength;
    }
  } catch {
    // keep what arrived
  } finally {
    void reader.cancel().catch(() => undefined);
  }
  const bytes = new Uint8Array(Math.min(total, limit));
  let offset = 0;
  for (const chunk of chunks) {
    const part = chunk.subarray(0, bytes.length - offset);
    bytes.set(part, offset);
    offset += part.byteLength;
    if (offset >= bytes.length) break;
  }
  return new TextDecoder().decode(bytes);
}

async function fetchIcon(url: string, minBytes: number): Promise<SourceIcon | null> {
  const response = await fetchPublic(url, { accept: "image/*" });
  if (!response) return null;
  const contentType = (response.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (!response.ok || !contentType.startsWith("image/")) { void response.body?.cancel(); return null; }
  const body = await readLimited(response, MAX_ICON_BYTES);
  return body && body.byteLength >= minBytes ? { body, contentType } : null;
}

/** The host's best declared icon, else its `/favicon.ico` when that is more than a placeholder, else null. */
export async function fetchSourceIcon(host: string): Promise<SourceIcon | null> {
  if (!isHostName(host)) return null;
  const home = `https://${host}/`;
  const page = await fetchPublic(home, { accept: "text/html" });
  let candidates: string[] = [];
  if (page?.ok && (page.headers.get("content-type") ?? "").includes("html")) {
    candidates = iconCandidates(await readPrefix(page, MAX_HTML_BYTES), page.url || home);
  } else {
    void page?.body?.cancel();
  }
  for (const candidate of candidates.slice(0, 4)) {
    const icon = await fetchIcon(candidate, 1);
    if (icon) return icon;
  }
  return fetchIcon(new URL("/favicon.ico", home).toString(), MIN_GUESSED_ICON_BYTES);
}
