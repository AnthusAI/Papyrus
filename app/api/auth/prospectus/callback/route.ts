import type { NextRequest } from "next/server";
import { handleProspectusSignInCallback } from "../../../../../lib/prospectus-sign-in-routes";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleProspectusSignInCallback(request);
}
