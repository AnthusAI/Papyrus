import type { NextRequest } from "next/server";
import { handleNewsletterPreferences } from "../../../../lib/newsletter-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNewsletterPreferences(request);
}

export function POST(request: NextRequest) {
  return handleNewsletterPreferences(request);
}
