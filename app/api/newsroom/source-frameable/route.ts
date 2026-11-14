import { NextResponse } from "next/server";
import { checkSourceFrameable } from "../../../../lib/source-frameable";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET ?url=<source page> -> { frameable }: whether the newsroom can show that page's live preview. Cached for a day. */
export async function GET(request: Request) {
  const url = new URL(request.url).searchParams.get("url") ?? "";
  const frameable = url ? await checkSourceFrameable(url) : false;
  return NextResponse.json({ frameable }, { headers: { "cache-control": "public, max-age=86400" } });
}
