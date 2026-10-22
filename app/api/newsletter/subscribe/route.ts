import type { NextRequest } from "next/server";
import { handleNewsletterSubscribe } from "../../../../lib/newsletter-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return handleNewsletterSubscribe(request);
}
