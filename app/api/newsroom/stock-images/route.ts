import type { NextRequest } from "next/server";
import { handleStockImageRequest } from "../../../../lib/stock-images/route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Editor-only stock image search and copy (cover picker). See lib/stock-images/route.ts for who may call and what it does. */
export function POST(request: NextRequest) {
  return handleStockImageRequest(request);
}

export function GET(request: NextRequest) {
  return handleStockImageRequest(request);
}
