import type { NextRequest } from "next/server";
import { handleNewsletterState } from "../../../../lib/newsletter-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNewsletterState(request);
}
