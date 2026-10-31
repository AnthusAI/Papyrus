import type { NextRequest } from "next/server";
import { handleCliEnroll } from "../../../lib/prospectus-enroll";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return handleCliEnroll(request);
}

export function GET(request: NextRequest) {
  return handleCliEnroll(request);
}
