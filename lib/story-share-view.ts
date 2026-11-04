/**
 * What a share link answers over HTTP (docs/story-share-links.md). Pure builders live here so the attack cases are tested without a server;
 * `askStoryShare` is the one place that talks to the newsroom's function, as the visitor's own session when there is one and as a guest otherwise.
 *
 * Every response from a share route carries the same three headers, and a link that does not work is always the same plain page.
 */

export const SHARE_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export const SHARE_HEADERS = {
  "X-Robots-Tag": "noindex, nofollow",
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
} as const;

const NOT_AVAILABLE_TITLE = "This link is not available";

export type ShareAnswer =
  | { state: "ok"; html: string }
  | { state: "unavailable" }
  | { state: "sign-in" }
  | { state: "published"; address: string | null };

export type MediaAnswer =
  | { state: "ok"; source: "site"; url: string }
  | { state: "ok"; source: "media"; storagePath: string }
  | { state: "unavailable" };

const UNAVAILABLE: { state: "unavailable" } = { state: "unavailable" };

function parsed(raw: unknown): Record<string, unknown> | null {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** Anything that is not exactly one of the four known answers is the plain "not available" one. */
export function parseShareAnswer(raw: unknown): ShareAnswer {
  const value = parsed(raw);
  if (!value) return UNAVAILABLE;
  if (value.state === "ok" && typeof value.html === "string" && value.html !== "") return { state: "ok", html: value.html };
  if (value.state === "sign-in") return { state: "sign-in" };
  if (value.state === "published") return { state: "published", address: typeof value.address === "string" && /^https:\/\/[^\s"'<>]+$/.test(value.address) ? value.address : null };
  return UNAVAILABLE;
}

export function parseMediaAnswer(raw: unknown): MediaAnswer {
  const value = parsed(raw);
  if (!value || value.state !== "ok") return UNAVAILABLE;
  if (value.source === "site" && typeof value.url === "string" && /^https:\/\/[^\s"'<>\\]+$/.test(value.url)) return { state: "ok", source: "site", url: value.url };
  if (value.source === "media" && typeof value.storagePath === "string" && /^media\/[^\\\0]+$/.test(value.storagePath) && !value.storagePath.split("/").includes("..")) {
    return { state: "ok", source: "media", storagePath: value.storagePath };
  }
  return UNAVAILABLE;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function plainPage(title: string, lines: string[], link?: { href: string; label: string }): string {
  const body = lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("");
  const anchor = link ? `<p><a href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a></p>` : "";
  return (
    `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer"><title>${escapeHtml(title)}</title>` +
    `<style>:root{color-scheme:light dark}body{margin:0;display:grid;min-height:100vh;place-items:center;font:1rem/1.5 system-ui,sans-serif;background:Canvas;color:CanvasText}` +
    `main{max-width:32rem;padding:1.5rem}h1{font-size:1.4rem;margin:0 0 .75rem}a{color:inherit}</style></head>` +
    `<body><main><h1>${escapeHtml(title)}</h1>${body}${anchor}</main></body></html>`
  );
}

function htmlResponse(html: string, status: number, extra: Record<string, string> = {}): Response {
  return new Response(html, { status, headers: { "Content-Type": "text/html; charset=utf-8", ...SHARE_HEADERS, ...extra } });
}

/** The one page a stranger sees for a link that is unknown, expired, revoked or ended: the same words, the same status, the same headers. */
export function unavailableResponse(): Response {
  return htmlResponse(plainPage(NOT_AVAILABLE_TITLE, ["Ask the person who sent it for a new one."]), 404);
}

export function shareResponse(answer: ShareAnswer, options: { signInPath: string }): Response {
  if (answer.state === "ok") return htmlResponse(answer.html, 200);
  if (answer.state === "sign-in") {
    return new Response(null, { status: 302, headers: { Location: options.signInPath, ...SHARE_HEADERS } });
  }
  if (answer.state === "published") {
    return htmlResponse(
      plainPage(
        "This draft is now published",
        ["The draft that was shared here has been published, so this link has ended."],
        answer.address ? { href: answer.address, label: "Read the published story" } : undefined,
      ),
      200,
    );
  }
  return unavailableResponse();
}

const IMAGE_TYPE = /^image\/(?:png|jpe?g|gif|webp|avif|svg\+xml)(?:;.*)?$/i;

export type MediaDependencies = {
  signStorageUrl: (storagePath: string) => Promise<string>;
  fetchUpstream: (url: string) => Promise<Response>;
};

/** Streams one picture of a shared page. Only what the function approved, only images, and never anything the browser could run. */
export async function mediaResponse(answer: MediaAnswer, dependencies: MediaDependencies): Promise<Response> {
  if (answer.state !== "ok") return unavailableResponse();
  try {
    const url = answer.source === "site" ? answer.url : await dependencies.signStorageUrl(answer.storagePath);
    const upstream = await dependencies.fetchUpstream(url);
    const type = upstream.headers.get("content-type") ?? "";
    if (!upstream.ok || !IMAGE_TYPE.test(type)) return unavailableResponse();
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": type,
        ...SHARE_HEADERS,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
      },
    });
  } catch {
    return unavailableResponse();
  }
}

/** Where a visitor with no session is sent to sign in; the page there sends them back to the link. */
export function signInPathFor(token: string, toPublicPath: (internalPath: string) => string): string {
  return toPublicPath(`/newsroom/share/${token}`);
}

export function apiPathFor(token: string): string {
  return `/api/share/${token}`;
}
