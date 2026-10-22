import type { NextRequest } from "next/server";
import { handleReaderRetiredSubjects } from "../../../../lib/reader-retirement-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleReaderRetiredSubjects(request);
}
