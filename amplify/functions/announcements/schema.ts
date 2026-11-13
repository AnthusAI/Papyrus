import { a } from "@aws-amplify/backend";
import { announcements } from "./resource";
import { functionHandler } from "../../data/function-handler";
export { ANNOUNCEMENT_MUTATION_OPERATIONS, ANNOUNCEMENT_QUERY_OPERATIONS } from "./operations";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API; announcements are off until the owner turns them on. The settings and the X connection
 * are kept in two models that only the function writes (admins may read them). The console reads and changes them through
 * the function, which checks the role again: editors read (queries), only admins change (mutations). No answer carries a secret.
 *
 * Settings use the same mechanism as the editorial check settings: one JSON document (`id: "settings"`) in a model.
 */
const query = () => a.query().arguments({ input: a.json() }).returns(a.json()).authorization((allow) => [allow.groups(editors)]).handler(functionHandler("announcements", announcements));
const mutation = () => a.mutation().arguments({ input: a.json() }).returns(a.json()).authorization((allow) => [allow.group("admin")]).handler(functionHandler("announcements", announcements));

export const announcementsSchemaDefinitions = {
  AnnouncementSettings: a
    .model({
      id: a.id().required(),
      settings: a.json().required(),
    })
    .disableOperations(["subscriptions"])
    .authorization((allow) => [allow.group("admin").to(["read"])]),
  /**
   * One announcement of a Story on the publication's X account: the audit row (who, what, when, post id, cost, mode, outcome). id = "<accountId>#<storyLineageId>",
   * created with a condition so a Story is announced once per account. The post text is in S3 (ModelAttachment role announcement_document). Editors and admins read;
   * the announcement pipeline writes.
   */
  Announcement: a
    .model({
      id: a.id().required(),
      accountId: a.string().required(),
      accountHandle: a.string(),
      storyLineageId: a.id().required(),
      storyItemId: a.id(),
      storyVersionNumber: a.integer(),
      channel: a.string().required(),
      state: a.string().required(),
      blockedReason: a.string(),
      mode: a.string().required(),
      trigger: a.string(),
      link: a.string(),
      weight: a.integer(),
      draftedBy: a.string(),
      checks: a.json(),
      postId: a.string(),
      postedAt: a.datetime(),
      cost: a.string(),
      attempts: a.integer(),
      round: a.integer(),
      error: a.string(),
      history: a.json(),
      withdrawnBy: a.string(),
      withdrawnAt: a.datetime(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("accountId").sortKeys(["createdAt"]).queryField("listAnnouncementsByAccountAndCreatedAt"),
    ])
    .disableOperations(["subscriptions"])
    .authorization((allow) => [allow.groups(editors).to(["read"])]),
  /** What an account spent on X in one billing cycle: id = "<accountId>#<cycle start date>", raised once for every charge Caducus records. */
  AnnouncementSpend: a
    .model({
      id: a.id().required(),
      accountId: a.string().required(),
      cycleStart: a.string().required(),
      total: a.string().required(),
      updatedAt: a.datetime().required(),
    })
    .disableOperations(["subscriptions"])
    .authorization((allow) => [allow.groups(editors).to(["read"])]),
  XConnection: a
    .model({
      id: a.id().required(),
      clientId: a.string(),
      secretSavedAt: a.string(),
      secretSavedBy: a.string(),
      accountId: a.string(),
      handle: a.string(),
      scopes: a.string().array(),
      status: a.string(),
      statusReason: a.string(),
      connectedAt: a.string(),
      connectedBy: a.string(),
      lastRefreshAt: a.string(),
      lastRefreshError: a.string(),
      leaseHolder: a.string(),
      leaseUntil: a.float(),
    })
    .disableOperations(["subscriptions"])
    .authorization((allow) => [allow.group("admin").to(["read"])]),
  announcementsSettings: query(),
  announcementsXStatus: query(),
  announcementsXUsage: query(),
  announcementsSaveSettings: mutation(),
  announcementsPause: mutation(),
  announcementsXSaveApp: mutation(),
  announcementsXBegin: mutation(),
  announcementsXComplete: mutation(),
  announcementsXDisconnect: mutation(),
};
