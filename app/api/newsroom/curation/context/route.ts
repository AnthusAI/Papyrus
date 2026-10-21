import type { NextRequest } from "next/server";
import { handleCurationRoute } from "../../../../../lib/curation-routes";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleCurationRoute(request, "context");
}
