// renameThread: the person who started a conversation, or an admin, gives it a new title. The browser's own update of a thread
// cannot change the title (the field is read and create only), so this is the one way. Nothing else about the thread changes.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

export function request(ctx) {
  const identity = ctx.identity;
  if (!identity || !identity.sub) util.error("Sign in to rename a conversation.", "Unauthorized");
  const title = typeof ctx.args.title === "string" ? ctx.args.title.trim() : "";
  if (!title) util.error("A title cannot be empty.", "BadRequest");
  const groups = identity.groups || [];
  const isAdmin = groups.indexOf("admin") >= 0;
  return ddb.update({
    key: { id: ctx.args.id },
    update: { title: ddb.operations.replace(title.slice(0, 120)) },
    condition: isAdmin ? { id: { attributeExists: true } } : { createdBySub: { eq: identity.sub } },
  });
}

export function response(ctx) {
  if (ctx.error) {
    if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
      util.error("Only the person who started this conversation, or an admin, can rename it.", "Unauthorized");
    }
    util.error(ctx.error.message, ctx.error.type);
  }
  return ctx.result;
}
