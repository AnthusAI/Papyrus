import type { NextRequest } from "next/server";
import { handleProspectusSignOut } from "../../../../../lib/prospectus-sign-in-routes";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return handleProspectusSignOut(request);
}
