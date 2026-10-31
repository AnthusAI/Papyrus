// setPublicHandle, step 3 of 3: write the checked handle (or remove the attribute, so the unique index holds only handles that
// are set) and the time. The condition refuses a profile that does not exist, so an update never creates one.
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
    if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") util.error("Your profile was not found.", "BadRequest");
    util.error(ctx.error.message, ctx.error.type);
  }
  return ctx.result;
}
