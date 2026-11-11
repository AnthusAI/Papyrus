import { COMPUTE_ROLE_ARN_ENVIRONMENT_VARIABLE, environmentOrConfigured } from "../../deploy-identifiers";
import {
  COMPUTE_ROLE_ARN,
  HOSTNAME,
  LOCAL_PART,
  NEWSLETTER_LIST_ID,
  NEWSLETTER_SITE_ID,
  SES_NAME,
  basePath,
  itemUrlStyle,
  matching,
  origin,
  record,
  resolveRule,
  resolveTheme,
  text,
  type ItemUrlStyle,
  type NewsletterRule,
  type NewsletterTheme,
} from "../newsletter/config";
import type { PluginRequest } from "../types";

export type NotificationsTheme = NewsletterTheme;

/** One list of stories a site announces: which published items it covers, and whether an admin approves first. */
export type NotificationsList = {
  id: string;
  name: string;
  description: string;
  rule: NewsletterRule;
  approval: "admin" | "none";
};

export type NotificationsConfig = {
  /** The site id: names the table, the functions and the SES configuration set. Matches the newsletter's sending stack SiteId. */
  siteId: string;
  /** The site's public https origin. */
  siteOrigin: string;
  /** The site's `urls.basePath` from projection.json, without slashes at either end. */
  basePath: string;
  /** The IAM role of the CMS app's server runtime: the only caller of the router function. */
  computeRoleArn: string;
  sendingDomain: string;
  fromAddress: string;
  fromName: string;
  theme: NotificationsTheme;
  lists: NotificationsList[];
  itemUrlStyle: ItemUrlStyle;
  /** `papyrus-<siteId>` unless overridden: the sending stack's configuration set, shared with the newsletter. */
  configurationSet: string;
};

const KNOWN_KEYS = [
  "name", "siteId", "siteOrigin", "basePath", "computeRoleArn", "sendingDomain", "fromAddress", "fromName", "theme", "lists",
  "itemUrlStyle", "configurationSet",
];
const LIST_KEYS = ["id", "name", "description", "rule", "approval"];

/** The helpers shared with the newsletter word their errors for it; this plugin says its own name. */
function inThisPlugin<T>(run: () => T): T {
  try {
    return run();
  } catch (error) {
    if (error instanceof Error) throw new Error(error.message.replace(/^newsletter plugin /, "notifications plugin "));
    throw error;
  }
}

function fail(message: string): never {
  throw new Error(`notifications plugin ${message}`);
}

function resolveList(raw: unknown, index: number): NotificationsList {
  const label = `lists[${index}]`;
  const list = record(raw, label, LIST_KEYS);
  const approval = list.approval === undefined ? "admin" : list.approval;
  if (approval !== "admin" && approval !== "none") fail(`${label}.approval must be "admin" or "none"`);
  return {
    id: matching(list.id, `${label}.id`, NEWSLETTER_LIST_ID, "lowercase letters, digits and hyphens, starting with a letter (at most 40 characters)"),
    name: text(list.name, `${label}.name`, 80),
    description: text(list.description, `${label}.description`, 300, { optional: true, fallback: "" }),
    rule: resolveRule(list.rule, `${label}.rule`),
    approval,
  };
}

export function resolveNotificationsConfig(request: PluginRequest): NotificationsConfig {
  return inThisPlugin(() => {
    const raw = record(typeof request === "string" ? { name: request } : request, "settings", KNOWN_KEYS);
    const siteId = matching(raw.siteId, "siteId", NEWSLETTER_SITE_ID, "a lowercase site id (letters, digits, hyphens), the SiteId of the sending stack");
    const computeRoleArn = environmentOrConfigured(COMPUTE_ROLE_ARN_ENVIRONMENT_VARIABLE, raw.computeRoleArn);
    if (typeof computeRoleArn !== "string" || !COMPUTE_ROLE_ARN.test(computeRoleArn)) {
      fail(`computeRoleArn must be the IAM role ARN of the CMS app's compute role (the CmsComputeRoleArn output); set the ${COMPUTE_ROLE_ARN_ENVIRONMENT_VARIABLE} branch environment variable or the plugin's computeRoleArn`);
    }
    const sendingDomain = matching(raw.sendingDomain, "sendingDomain", HOSTNAME, "a lowercase domain name such as news.example.com");
    const fromAddress = text(raw.fromAddress, "fromAddress", 254);
    const [local, domain, ...extra] = fromAddress.split("@");
    if (extra.length > 0 || !local || local.length > 64 || !LOCAL_PART.test(local) || domain !== sendingDomain) {
      fail(`fromAddress must be an address on ${sendingDomain} (lowercase, such as notifications@${sendingDomain})`);
    }
    if (!Array.isArray(raw.lists) || raw.lists.length === 0 || raw.lists.length > 20) fail("lists must be a list of 1 to 20 lists");
    const lists = raw.lists.map((entry, index) => resolveList(entry, index));
    const duplicates = lists.map((list) => list.id).filter((id, index, ids) => ids.indexOf(id) !== index);
    if (duplicates.length > 0) fail(`lists has duplicate ids: ${[...new Set(duplicates)].join(", ")}`);
    return {
      siteId,
      siteOrigin: origin(raw.siteOrigin),
      basePath: basePath(raw.basePath),
      computeRoleArn,
      sendingDomain,
      fromAddress,
      fromName: text(raw.fromName, "fromName", 80),
      theme: resolveTheme(raw.theme),
      lists,
      itemUrlStyle: itemUrlStyle(raw.itemUrlStyle),
      configurationSet: matching(raw.configurationSet, "configurationSet", SES_NAME, "an SES configuration set name", `papyrus-${siteId}`),
    };
  });
}
