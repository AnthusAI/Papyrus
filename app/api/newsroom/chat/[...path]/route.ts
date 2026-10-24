import type { NextRequest } from "next/server";
import { handlePapyrusHostedChatRequest } from "../../../../../lib/papyrus-hosted-chat";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handlePapyrusHostedChatRequest(request, path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handlePapyrusHostedChatRequest(request, path);
}
