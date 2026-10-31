import { fileURLToPath } from "node:url";
import { a } from "@aws-amplify/backend";

/**
 * Messages belong to their author, and the backend says so. The browser cannot create, edit or delete a Message through the
 * model (editors and admins only read it); it calls these four mutations, whose resolvers stamp the author from the signed-in
 * identity and check ownership against the stored `authorSub` in the same DynamoDB write. `renameThread` does the same for a
 * conversation's title. Functions and IAM callers (the router, procedures, the console responder, email, Slack) write the
 * model directly with their own grants, as before.
 *
 * Each resolver is one self-contained file (AppSync takes a single file and offers `@aws-appsync/utils` only).
 */
const people = (allow: any) => [allow.group("editor"), allow.group("admin")];
const adminsOnly = (allow: any) => [allow.group("admin")];
// Absolute paths: when a site loads this file from the package, its call site carries a loader query
// (`?tsx-namespace=...`) that Amplify cannot turn back into a directory, so a relative entry fails to deploy.
export const resolverEntry = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));
export const PROSPECTUS_DATA_SOURCE_NAME = "ProspectusAccounts";
/**
 * The first step of an account-scoped mutation's pipeline when a site turns `prospectusAuthorize` on: it asks Prospectus,
 * through the HTTP data source the backend adds for that flag, and refuses before any other step runs.
 */
export const prospectusAuthorizeStep = () =>
  a.handler.custom({ dataSource: PROSPECTUS_DATA_SOURCE_NAME, entry: resolverEntry("./resolvers/prospectus-authorize.js") });
const onMessages = (entry: string) => a.handler.custom({ dataSource: a.ref("Message"), entry: resolverEntry(entry) });
const onThreads = (entry: string) => a.handler.custom({ dataSource: a.ref("MessageThread"), entry: resolverEntry(entry) });
const guardedBy = (guarded: boolean, handler: ReturnType<typeof onMessages>) => (guarded ? [prospectusAuthorizeStep(), handler] : handler);

export const buildMessageActionsSchemaDefinitions = (prospectusAuthorize: boolean) => ({
  postMessage: a
    .mutation()
    .arguments({
      id: a.id().required(),
      threadId: a.id().required(),
      content: a.string(),
      summary: a.string(),
      parentMessageId: a.id(),
      sequenceNumber: a.integer(),
      messageKind: a.string().required(),
      messageDomain: a.string().required(),
      messageType: a.string(),
      role: a.string(),
      source: a.string(),
      authorLabel: a.string(),
      semanticLayer: a.string(),
      searchVisibility: a.string(),
      responseTarget: a.string(),
      responseStatus: a.string(),
      responseOwner: a.string(),
      responseStartedAt: a.datetime(),
      responseCompletedAt: a.datetime(),
      metadata: a.json(),
      newsroomFeedKey: a.string(),
    })
    .returns(a.ref("Message"))
    .authorization(people)
    .handler(guardedBy(prospectusAuthorize, onMessages("./resolvers/post-message.js"))),
  editMessage: a
    .mutation()
    .arguments({ id: a.id().required(), content: a.string().required(), summary: a.string() })
    .returns(a.ref("Message"))
    .authorization(people)
    .handler(guardedBy(prospectusAuthorize, onMessages("./resolvers/edit-message.js"))),
  deleteOwnMessage: a
    .mutation()
    .arguments({ id: a.id().required() })
    .returns(a.ref("Message"))
    .authorization(people)
    .handler(guardedBy(prospectusAuthorize, onMessages("./resolvers/delete-own-message.js"))),
  moderateMessage: a
    .mutation()
    .arguments({ id: a.id().required() })
    .returns(a.ref("Message"))
    .authorization(adminsOnly)
    .handler(guardedBy(prospectusAuthorize, onMessages("./resolvers/moderate-message.js"))),
  renameThread: a
    .mutation()
    .arguments({ id: a.id().required(), title: a.string().required() })
    .returns(a.ref("MessageThread"))
    .authorization(people)
    .handler(guardedBy(prospectusAuthorize, onThreads("./resolvers/rename-thread.js"))),
});

export const messageActionsSchemaDefinitions = buildMessageActionsSchemaDefinitions(false);
