import type { NextRequest } from "next/server";
import { handleReaderRequest } from "../../../../lib/reader-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleReaderRequest(request, "me");
}
