// setPublicHandle, step 5 of 5: release the claim nobody should hold. After a successful write that is the profile's old handle (when
// it changed or was cleared); after a failed write it is the handle just claimed (unless the person already held it), so no orphan
// claim is left. Both deletes carry the condition that the claim is still this profile's. Then a failed write is raised, and a
// successful one returns the profile.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

function claimToRelease(stash) {
  const previous = stash.previousHandle;
  const current = stash.handle;
  if (stash.writeFailure) return current !== null && current !== previous ? current : null;
  return previous !== null && previous !== current ? previous : null;
}

export function request(ctx) {
  const target = claimToRelease(ctx.stash);
  if (target === null) return ddb.get({ key: { id: ctx.stash.handle || ctx.stash.previousHandle || "none" } });
  return ddb.remove({ key: { id: target }, condition: { ownerId: { eq: ctx.stash.profileId } } });
}

export function response(ctx) {
  if (ctx.stash.writeFailure) util.error(ctx.stash.writeFailure.message, ctx.stash.writeFailure.type);
  if (ctx.error && ctx.error.type !== "DynamoDB:ConditionalCheckFailedException") util.error(ctx.error.message, ctx.error.type);
  return ctx.stash.profile;
}
