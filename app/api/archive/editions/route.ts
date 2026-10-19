import { NextResponse } from "next/server";
import { editionsEnabled } from "../../../../lib/site-brand";
import { loadArchiveEditionPreviews, clampArchiveLimit } from "../../../../lib/archive-data";
import { ARCHIVE_BATCH_SIZE } from "../../../../lib/archive-types";

// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 60;

export async function GET(request: Request) {
  if (!editionsEnabled()) return new NextResponse(null, { status: 404 });
  const url = new URL(request.url);
  const cursor = url.searchParams.get("cursor");
  const requestedLimit = Number(url.searchParams.get("limit") ?? ARCHIVE_BATCH_SIZE);
  const payload = await loadArchiveEditionPreviews({
    limit: clampArchiveLimit(requestedLimit),
    nextToken: cursor,
  });

  return NextResponse.json(payload);
}
