// deleteOwnMessage: the author deletes their own Message. A soft delete: the Message stays (replies keep their place) marked
// deleted, with when and by whom. Nothing is removed.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  const identity = ctx.identity;
  if (!identity || !identity.sub) util.error("Sign in to delete a message.", "Unauthorized");
  const now = util.time.nowISO8601();
  return ddb.update({
    key: { id: ctx.args.id },
    update: {
      status: ddb.operations.replace("deleted"),
      deletedAt: ddb.operations.replace(now),
      deletedBySub: ddb.operations.replace(identity.sub),
      updatedAt: ddb.operations.replace(now),
    },
    condition: { authorSub: { eq: identity.sub }, status: { ne: "deleted" } },
  });
}

export function response(ctx) {
  if (ctx.error) {
    if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
      util.error("Only the author can delete their own message, and it may already be deleted.", "Unauthorized");
    }
    util.error(ctx.error.message, ctx.error.type);
  }
  return ctx.result;
}
