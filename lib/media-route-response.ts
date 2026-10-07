const PROXIED_IMAGE_EXTENSIONS = new Set(["jpg", "jpeg", "png", "gif", "webp", "avif", "svg"]);

export type MediaRouteDependencies = {
  signStorageUrl: (storagePath: string) => Promise<string>;
  fetchUpstream: (signedUrl: string) => Promise<Response>;
};

export function isProxiedImagePath(storagePath: string): boolean {
  const lastSegment = storagePath.split("/").pop() ?? "";
  const dotIndex = lastSegment.lastIndexOf(".");
  if (dotIndex < 0) {
    return false;
  }
  return PROXIED_IMAGE_EXTENSIONS.has(lastSegment.slice(dotIndex + 1).toLowerCase());
}

export async function buildMediaRouteResponse(
  storagePath: string,
  dependencies: MediaRouteDependencies,
): Promise<Response> {
  const signedUrl = await dependencies.signStorageUrl(storagePath);

  if (!isProxiedImagePath(storagePath)) {
    return new Response(null, {
      status: 307,
      headers: { location: signedUrl, "cache-control": "private, max-age=300" },
    });
  }

  const upstream = await dependencies.fetchUpstream(signedUrl);
  if (!upstream.ok) {
    return Response.json(
      { error: `Upstream media fetch failed (${upstream.status}).` },
      { status: upstream.status === 404 ? 404 : 502 },
    );
  }

  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  headers.set("cache-control", "public, max-age=3600, stale-while-revalidate=86400");
  return new Response(upstream.body, { status: 200, headers });
}
