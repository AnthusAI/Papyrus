// setPublicHandle, step 2 of 5: read the caller's own profile so the handle it holds now is known, which is the claim to release
// once a new handle is claimed. A profile that does not exist is refused here, before any claim is made.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  return ddb.get({ key: { id: ctx.stash.profileId } });
}

export function response(ctx) {
  if (ctx.error) util.error(ctx.error.message, ctx.error.type);
  if (!ctx.result) util.error("Your profile was not found.", "BadRequest");
  ctx.stash.previousHandle = typeof ctx.result.publicHandle === "string" && ctx.result.publicHandle ? ctx.result.publicHandle : null;
  return ctx.result;
}
