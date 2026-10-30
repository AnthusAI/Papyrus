// moderateMessage: an admin removes anyone's Message. The same soft delete as the author's, with no change to the text, and only
// for the admin group (checked here as well as by the mutation's authorization).
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  const identity = ctx.identity;
  if (!identity || !identity.sub) util.error("Sign in to moderate a message.", "Unauthorized");
  const groups = identity.groups || [];
  if (groups.indexOf("admin") < 0) util.error("Only an admin can delete someone else's message.", "Unauthorized");
  const now = util.time.nowISO8601();
  return ddb.update({
    key: { id: ctx.args.id },
    update: {
      status: ddb.operations.replace("deleted"),
      deletedAt: ddb.operations.replace(now),
      deletedBySub: ddb.operations.replace(identity.sub),
      updatedAt: ddb.operations.replace(now),
    },
    condition: { id: { attributeExists: true }, status: { ne: "deleted" } },
  });
}

export function response(ctx) {
  if (ctx.error) {
    if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
      util.error("That message does not exist or is already deleted.", "NotFound");
    }
    util.error(ctx.error.message, ctx.error.type);
  }
  return ctx.result;
}
