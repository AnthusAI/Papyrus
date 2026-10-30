import type { NextRequest } from "next/server";
import { handleCliLoginPage } from "../../../lib/cli-login-pages";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return handleCliLoginPage(request);
}

export function POST(request: NextRequest) {
  return handleCliLoginPage(request);
}
