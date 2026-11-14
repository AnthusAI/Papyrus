// setPublicHandle, step 4 of 5: write the claimed handle (or remove the attribute, so the profile holds only handles that are set)
// and the time. The condition refuses a profile that does not exist, so an update never creates one. A failed write does not stop
// the pipeline: the failure is kept in the stash so the next step can release the claim that was just made, and then raises it.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  const handle = ctx.stash.handle;
  return ddb.update({
    key: { id: ctx.stash.profileId },
    update: {
      publicHandle: handle === null ? ddb.operations.remove() : ddb.operations.replace(handle),
      updatedAt: ddb.operations.replace(util.time.nowISO8601()),
    },
    condition: { id: { attributeExists: true } },
  });
}

export function response(ctx) {
  if (ctx.error) {
    const missing = ctx.error.type === "DynamoDB:ConditionalCheckFailedException";
    ctx.stash.writeFailure = { message: missing ? "Your profile was not found." : ctx.error.message, type: missing ? "BadRequest" : ctx.error.type };
    return null;
  }
  ctx.stash.profile = ctx.result;
  return ctx.result;
}
