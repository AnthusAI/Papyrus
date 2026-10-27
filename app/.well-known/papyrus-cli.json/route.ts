import type { NextRequest } from "next/server";
import { handleCliLoginDiscovery } from "../../../lib/cli-login-discovery";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleCliLoginDiscovery(request);
}
