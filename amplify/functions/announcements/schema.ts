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
