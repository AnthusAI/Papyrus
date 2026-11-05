import type { NextRequest } from "next/server";
import { signStorageUrl } from "../../../../../lib/reader-storage-url";
import { SHARE_TOKEN_PATTERN, mediaResponse, parseMediaAnswer, unavailableResponse } from "../../../../../lib/story-share-view";
import { askStoryShare } from "../../../../../lib/story-share-server";

export const dynamic = "force-dynamic";

type ShareMediaContext = { params: Promise<{ token: string }> };

/** One picture of a shared page. The function answers only for a picture that page asked for, of the version the link shows; anything else is the plain "not available". */
export async function GET(request: NextRequest, context: ShareMediaContext): Promise<Response> {
  const { token } = await context.params;
  const reference = request.nextUrl.searchParams.get("u");
  if (!SHARE_TOKEN_PATTERN.test(token) || !reference || reference.length > 2048) return unavailableResponse();
  try {
    const answer = parseMediaAnswer(await askStoryShare("viewStoryShareMedia", { token, reference }));
    return await mediaResponse(answer, {
      signStorageUrl,
      fetchUpstream: (url) => fetch(url, { cache: "no-store", redirect: "error" }),
    });
  } catch {
    return unavailableResponse();
  }
}
