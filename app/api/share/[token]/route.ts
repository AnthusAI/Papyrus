import { toPublicNewsroomPath } from "../../../../lib/newsroom-base-path";
import { SHARE_TOKEN_PATTERN, parseShareAnswer, shareResponse, signInPathFor, unavailableResponse } from "../../../../lib/story-share-view";
import { askStoryShare } from "../../../../lib/story-share-server";

export const dynamic = "force-dynamic";

type ShareRouteContext = { params: Promise<{ token: string }> };

/** A shared Story in the website's public layout, labelled DRAFT (docs/story-share-links.md). The token is the credential; the newsroom's function decides, and every unusable link is the same page. */
export async function GET(_request: Request, context: ShareRouteContext): Promise<Response> {
  const { token } = await context.params;
  if (!SHARE_TOKEN_PATTERN.test(token)) return unavailableResponse();
  try {
    const answer = parseShareAnswer(await askStoryShare("viewStoryShare", { token }));
    return shareResponse(answer, { signInPath: signInPathFor(token, toPublicNewsroomPath) });
  } catch {
    return unavailableResponse();
  }
}

