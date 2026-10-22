import type { NextRequest } from "next/server";
import { handleNewsletterConfirmPage, handleNewsletterConfirmPost } from "../../../../lib/newsletter-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNewsletterConfirmPage(request);
}

export function POST(request: NextRequest) {
  return handleNewsletterConfirmPost(request);
}
