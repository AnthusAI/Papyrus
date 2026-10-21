import type { NextRequest } from "next/server";
import { handleCurationRoute } from "../../../../../lib/curation-routes";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return handleCurationRoute(request, "priming");
}
