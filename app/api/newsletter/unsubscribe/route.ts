import type { NextRequest } from "next/server";
import { handleNewsletterUnsubscribe } from "../../../../lib/newsletter-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNewsletterUnsubscribe(request);
}

export function POST(request: NextRequest) {
  return handleNewsletterUnsubscribe(request);
}
