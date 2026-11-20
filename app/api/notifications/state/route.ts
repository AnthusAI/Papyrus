import type { NextRequest } from "next/server";
import { handleNotificationsState } from "../../../../lib/notifications-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleNotificationsState(request);
}
