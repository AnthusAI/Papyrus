// editMessage: a person changes the text of their own Message, and no one else's. The condition is checked by DynamoDB against the
// stored authorSub in the same write, so there is no window between the check and the change. A deleted Message cannot be edited.
// Authorship cannot be reassigned: the update never touches authorSub.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  const identity = ctx.identity;
  if (!identity || !identity.sub) util.error("Sign in to edit a message.", "Unauthorized");
  const content = typeof ctx.args.content === "string" ? ctx.args.content.trim() : "";
  if (!content) util.error("A message cannot be empty.", "BadRequest");
  const now = util.time.nowISO8601();
  return ddb.update({
    key: { id: ctx.args.id },
    update: {
      content: ddb.operations.replace(content),
      summary: ddb.operations.replace(ctx.args.summary ? ctx.args.summary : content.slice(0, 120)),
      editedAt: ddb.operations.replace(now),
      updatedAt: ddb.operations.replace(now),
    },
    condition: { authorSub: { eq: identity.sub }, status: { ne: "deleted" } },
  });
}

export function response(ctx) {
  if (ctx.error) {
    if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
      util.error("Only the author can edit a message, and a deleted message cannot be edited.", "Unauthorized");
    }
    util.error(ctx.error.message, ctx.error.type);
  }
  return ctx.result;
}
