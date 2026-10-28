import { fetchSourceIcon } from "../../../../lib/source-icon";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET ?host=<source host> -> the source's own icon, or 404 so the newsroom shows its letter mark. Cached for a week. */
export async function GET(request: Request) {
  const host = (new URL(request.url).searchParams.get("host") ?? "").toLowerCase();
  const icon = host ? await fetchSourceIcon(host) : null;
  if (!icon) return new Response(null, { status: 404, headers: { "cache-control": "public, max-age=86400" } });
  return new Response(icon.body, {
    headers: {
      "cache-control": "public, max-age=604800",
      "content-type": icon.contentType,
      // An SVG icon is shown only through <img>, but never let it run as a document on our origin.
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
      "x-content-type-options": "nosniff",
    },
  });
}
