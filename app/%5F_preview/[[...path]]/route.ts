import type { NextRequest } from "next/server";
import { streamPreviewObject } from "@/lib/staging-preview-object";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  return streamPreviewObject(request.nextUrl.pathname);
}
