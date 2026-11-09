import type { NextRequest } from "next/server";
import { handleNotificationsConfirm } from "../../../../lib/notifications-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNotificationsConfirm(request);
}

export function POST(request: NextRequest) {
  return handleNotificationsConfirm(request);
}
