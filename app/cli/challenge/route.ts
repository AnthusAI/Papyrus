import type { NextRequest } from "next/server";
import { handleCliChallenge } from "../../../lib/prospectus-enroll";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleCliChallenge(request);
}

export function POST(request: NextRequest) {
  return handleCliChallenge(request);
}
