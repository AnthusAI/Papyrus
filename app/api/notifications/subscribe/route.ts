import type { NextRequest } from "next/server";
import { handleNotificationsSubscribe } from "../../../../lib/notifications-api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return handleNotificationsSubscribe(request);
}
