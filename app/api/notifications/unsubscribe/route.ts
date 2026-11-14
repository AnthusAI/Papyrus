import type { NextRequest } from "next/server";
import { handleNotificationsUnsubscribe } from "../../../../lib/notifications-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNotificationsUnsubscribe(request);
}

export function POST(request: NextRequest) {
  return handleNotificationsUnsubscribe(request);
}
