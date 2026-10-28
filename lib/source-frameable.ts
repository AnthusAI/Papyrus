import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

/**
 * Whether a source page lets another site show it in a frame. Most news sites refuse (X-Frame-Options or a CSP frame-ancestors
 * rule), and a refused frame is just an empty box, which the browser cannot detect from outside. So the newsroom asks here,
 * on the server, before it shows a web page's live preview.
 */

/** True when the response headers allow framing by any site. A rule naming specific origins is treated as a refusal. */
export function frameableFromHeaders(headers: Headers): boolean {
  const xfo = headers.get("x-frame-options")?.trim().toLowerCase();
  if (xfo && (xfo.includes("deny") || xfo.includes("sameorigin") || xfo.startsWith("allow-from"))) return false;
  const csp = headers.get("content-security-policy");
  if (csp) {
    for (const directive of csp.split(";")) {
      const [name, ...sources] = directive.trim().split(/\s+/);
      if (name?.toLowerCase() !== "frame-ancestors") continue;
      if (!sources.some((source) => source === "*" || source === "https:" || source === "http:")) return false;
    }
  }
  return true;
}

/** Loopback, private, link-local and other non-public addresses, which the server must never be made to fetch. */
export function isPrivateAddress(address: string): boolean {
  const v4 = address.startsWith("::ffff:") ? address.slice(7) : address;
  if (isIP(v4) === 4) {
    const [a, b] = v4.split(".").map(Number);
    return a === 0 || a === 10 || a === 127 || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254)
      || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || a >= 224;
  }
  const v6 = address.toLowerCase();
  return v6 === "::" || v6 === "::1" || v6.startsWith("fc") || v6.startsWith("fd") || v6.startsWith("fe80");
}

/** A plain public http(s) address on the default port whose host resolves only to public addresses, else null. */
export async function publicHttpUrl(raw: string): Promise<URL | null> {
  let url: URL;
  try { url = new URL(raw); } catch { return null; }
  if ((url.protocol !== "https:" && url.protocol !== "http:") || url.port || url.username || url.password) return null;
  try {
    const addresses = isIP(url.hostname) ? [{ address: url.hostname }] : await lookup(url.hostname, { all: true });
    return addresses.length && addresses.every(({ address }) => !isPrivateAddress(address)) ? url : null;
  } catch {
    return null;
  }
}

/** Asks the page itself. Anything that fails (bad address, error status, timeout, too many redirects) counts as not frameable. */
export async function checkSourceFrameable(raw: string, { timeoutMs = 5000, maxRedirects = 4 } = {}): Promise<boolean> {
  let next = await publicHttpUrl(raw);
  for (let hop = 0; next && hop <= maxRedirects; hop += 1) {
    let response: Response;
    try {
      response = await fetch(next, { method: "GET", redirect: "manual", signal: AbortSignal.timeout(timeoutMs), headers: { accept: "text/html" } });
    } catch {
      return false;
    }
    void response.body?.cancel();
    const location = response.headers.get("location");
    if (response.status >= 300 && response.status < 400 && location) {
      next = await publicHttpUrl(new URL(location, next).toString());
      continue;
    }
    return response.ok && frameableFromHeaders(response.headers);
  }
  return false;
}
