import { NextResponse } from "next/server";
import { isGuestReadableStoragePath, signStorageUrl } from "../../../../lib/reader-storage-url";

export const dynamic = "force-dynamic";

type MediaRouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

export async function GET(_request: Request, context: MediaRouteContext) {
  const { path } = await context.params;
  const storagePath = path.map((segment) => decodeURIComponent(segment)).join("/");
  if (!isGuestReadableStoragePath(storagePath)) {
    return NextResponse.json({ error: "Forbidden storage path." }, { status: 403 });
  }

  const signedUrl = await signStorageUrl(storagePath);
  const upstream = await fetch(signedUrl, { cache: "no-store" });
  if (!upstream.ok) {
    return NextResponse.json(
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
  return new NextResponse(upstream.body, { status: 200, headers });
}
