import type { NextRequest } from "next/server";
import { handleNewsletterConfirm } from "../../../../lib/newsletter-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNewsletterConfirm(request);
}

export function POST(request: NextRequest) {
  return handleNewsletterConfirm(request);
}
