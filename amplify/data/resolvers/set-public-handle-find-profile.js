// setPublicHandle, step 1 of 3: the profile to change is the signed-in person's own. The mutation takes no profile id; the profile
// comes from the identity's sub through the UserIdentity index, so nobody (an admin included) can name someone else's profile.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  const identity = ctx.identity;
  if (!identity || !identity.sub) util.error("Sign in to set a public handle.", "Unauthorized");
  return ddb.query({ index: "userIdentitiesByCognitoSub", query: { cognitoSub: { eq: identity.sub } } });
}

export function response(ctx) {
  if (ctx.error) util.error(ctx.error.message, ctx.error.type);
  const items = ctx.result.items || [];
  let profileId = null;
  for (const item of items) {
    if (item.status === "active" && item.userProfileId) profileId = item.userProfileId;
  }
  if (!profileId) util.error("Open Settings once so your profile exists, then try again.", "BadRequest");
  ctx.stash.profileId = profileId;
  return { profileId: profileId };
}
