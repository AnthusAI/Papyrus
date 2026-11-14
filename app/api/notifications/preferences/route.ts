import type { NextRequest } from "next/server";
import { handleNotificationsPreferences } from "../../../../lib/notifications-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNotificationsPreferences(request);
}

export function POST(request: NextRequest) {
  return handleNotificationsPreferences(request);
}
