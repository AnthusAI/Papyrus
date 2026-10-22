import type { NextRequest } from "next/server";
import { handleReaderRequest } from "../../../../lib/reader-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return handleReaderRequest(request, "handle");
}
