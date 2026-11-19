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
   * An Announcement: the decision to say something about one or more Stories (docs/announcement-records.md). It knows nothing about channels and holds no approval;
   * a Delivery holds both. id is made from the once-only key (dedupeKey), and created with a condition, so a decision is made once. The Stories it is about are
   * `announces` relations, with the version looked at. Short fields only: no text. The model named `Announcement` (the old X row shape, with its
   * account index and round counter) is gone: an X post is an Announcement with one Delivery. Editors and admins read; the announcement pipeline writes.
   */
  AnnouncementDecision: a
    .model({
      id: a.id().required(),
      tenantId: a.string(),
      dedupeKey: a.string().required(),
      kind: a.string().required(),
      state: a.string().required(),
      releaseAt: a.datetime().required(),
      createdBy: a.string().required(),
      trigger: a.string(),
      history: a.json(),
      revision: a.integer().required(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("tenantId").sortKeys(["id"]).queryField("listAnnouncementDecisionsByTenant"),
      index("dedupeKey").sortKeys(["createdAt"]).queryField("listAnnouncementDecisionsByDedupeKeyAndCreatedAt"),
      index("state").sortKeys(["releaseAt"]).queryField("listAnnouncementDecisionsByStateAndReleaseAt"),
    ])
    .disableOperations(["subscriptions"])
    .authorization((allow) => [allow.groups(editors).to(["read"])]),
  /**
   * A Delivery: one channel's version of an Announcement (docs/announcement-records.md). The words and any picture are files in S3 (textKey, imageKey, contentHash);
   * the row never holds text. id is `<announcement>#<channel>#<account>#g<generation>`, created with a condition: one live Delivery for each Announcement, channel and
   * account, and a correction is the next generation, written with `supersedes`. Every edit is a new version: `versions` is the log (each version's file, key, hash, who saved it and which
   * version it replaced; the words themselves are files in S3) and `candidates` the texts and pictures kept beside the draft. Approval lives here, per Delivery. Every wait is a named time (releaseAt, lockAt,
   * nextAttemptAt with waitingFor); dueAt is the earliest of them and, with dueKey, is present only while one is pending, so the due index is sparse.
   */
  Delivery: a
    .model({
      id: a.id().required(),
      tenantId: a.string(),
      announcementId: a.string().required(),
      channel: a.string().required(),
      accountId: a.string().required(),
      accountKey: a.string().required(),
      audience: a.string().array(),
      mode: a.string().required(),
      state: a.string().required(),
      blockedReason: a.string(),
      generation: a.integer().required(),
      version: a.integer().required(),
      textKey: a.string(),
      imageKey: a.string(),
      contentHash: a.string(),
      draftedBy: a.string(),
      checks: a.json(),
      versions: a.json(),
      candidates: a.json(),
      approval: a.string().required(),
      approvalPolicy: a.string().required(),
      approvedVersion: a.integer(),
      approvedBy: a.string(),
      approvedAt: a.datetime(),
      releaseAt: a.datetime().required(),
      lockAt: a.datetime().required(),
      lockedAt: a.datetime(),
      lockedVersion: a.integer(),
      preferredVersion: a.integer(),
      machineVersion: a.integer(),
      exampleScope: a.string(),
      exampleState: a.string(),
      exampleAt: a.datetime(),
      exampleKey: a.string(),
      nextAttemptAt: a.datetime(),
      waitingFor: a.string(),
      dueAt: a.datetime(),
      dueKey: a.string(),
      resultUrl: a.string(),
      providerId: a.string(),
      cost: a.string(),
      counts: a.json(),
      attempts: a.json(),
      supersedes: a.string(),
      supersededBy: a.string(),
      history: a.json(),
      revision: a.integer().required(),
      createdAt: a.datetime().required(),
      updatedAt: a.datetime().required(),
    })
    .secondaryIndexes((index) => [
      index("tenantId").sortKeys(["id"]).queryField("listDeliveriesByTenant"),
      index("announcementId").sortKeys(["createdAt"]).queryField("listDeliveriesByAnnouncementAndCreatedAt"),
      index("accountKey").sortKeys(["createdAt"]).queryField("listDeliveriesByAccountKeyAndCreatedAt"),
      index("dueKey").sortKeys(["dueAt"]).queryField("listDeliveriesByDueKeyAndDueAt"),
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
