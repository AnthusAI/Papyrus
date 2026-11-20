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
  /**
   * What the list is for. `story.published` (the default) sends each matching story. `roundup` is a periodic issue's list: it is never
   * sent each story, so it carries no rule. A newsletter roundup list keeps its id and becomes a `roundup` list when its subscribers move (PPY-6b2d35).
   */
  kind?: "story.published" | "roundup";
  /** The cadence family: lists that carry the same items at different cadences share one, and a reader holds one list of a family. None: its own family. */
  family?: string;
  /** `each`, `daily` or `weekly`, as in the site's `lists` document. A reader's switch between lists of a family waits for the next period start of its periodic list. */
  cadence?: "each" | "daily" | "weekly";
  /** A periodic list's local send time (`time`, and `day` for a weekly list) and IANA time zone. */
  sendAt?: { time: string; day?: string };
  timeZone?: string;
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
  /** The sentence the subscribe form shows. A signup must carry exactly this wording; Caducus stores its hash as consent evidence. */
  consent: string;
  /** How long a stranger's address is held unconfirmed and the confirmation link works, in hours (default 72, the newsletter's promise). */
  confirmWindowHours: number;
  itemUrlStyle: ItemUrlStyle;
  /** `papyrus-<siteId>` unless overridden: the sending stack's configuration set, shared with the newsletter. */
  configurationSet: string;
  /**
   * Honour the old newsletter's manage and unsubscribe links (they were mailed with the newsletter's tokens) until the date the migration
   * gave them. Dated: set only while that period runs, and removed with `src/papyrus_content/notifications/legacy_links.py` (see that file).
   */
  legacyNewsletterLinks: boolean;
};

const KNOWN_KEYS = [
  "name", "siteId", "siteOrigin", "basePath", "computeRoleArn", "sendingDomain", "fromAddress", "fromName", "theme", "lists",
  "itemUrlStyle", "configurationSet", "consent", "confirmWindowHours", "legacyNewsletterLinks",
];
const LIST_KEYS = ["id", "name", "description", "rule", "approval", "kind", "family", "cadence", "sendAt", "timeZone"];
const CADENCES = ["each", "daily", "weekly"];
const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

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
  const kind = list.kind === undefined ? undefined : list.kind;
  if (kind !== undefined && kind !== "story.published" && kind !== "roundup") fail(`${label}.kind must be "story.published" or "roundup"`);
  if (kind === "roundup" && list.rule !== undefined) fail(`${label} is a roundup list, which is never sent each story, so it names no rule`);
  const family = list.family === undefined ? undefined : matching(list.family, `${label}.family`, NEWSLETTER_LIST_ID, "lowercase letters, digits and hyphens, starting with a letter");
  const cadence = list.cadence === undefined ? undefined : list.cadence;
  if (cadence !== undefined && !CADENCES.includes(cadence as string)) fail(`${label}.cadence must be one of: ${CADENCES.join(", ")}`);
  const periodic = cadence === "daily" || cadence === "weekly";
  if (periodic) {
    const sendAt = record(list.sendAt, `${label}.sendAt`, ["time", "day"]);
    matching(sendAt.time, `${label}.sendAt.time`, /^([01]\d|2[0-3]):[0-5]\d$/, "a local time of day such as 06:00");
    if (cadence === "weekly" && !WEEKDAYS.includes(sendAt.day as string)) fail(`${label}.sendAt.day must be a weekday name: ${WEEKDAYS.join(", ")}`);
    if (cadence === "daily" && sendAt.day !== undefined) fail(`${label}.sendAt.day is for a weekly list`);
    text(list.timeZone, `${label}.timeZone`, 64);
  } else if (list.sendAt !== undefined || list.timeZone !== undefined) {
    fail(`${label} is not a periodic list, so it names no sendAt or timeZone`);
  }
  return {
    id: matching(list.id, `${label}.id`, NEWSLETTER_LIST_ID, "lowercase letters, digits and hyphens, starting with a letter (at most 40 characters)"),
    name: text(list.name, `${label}.name`, 80),
    description: text(list.description, `${label}.description`, 300, { optional: true, fallback: "" }),
    rule: resolveRule(list.rule, `${label}.rule`),
    approval,
    ...(kind === undefined ? {} : { kind: kind as NotificationsList["kind"] }),
    ...(family === undefined ? {} : { family }),
    ...(cadence === undefined ? {} : { cadence: cadence as NotificationsList["cadence"] }),
    ...(periodic ? { sendAt: list.sendAt as NotificationsList["sendAt"], timeZone: list.timeZone as string } : {}),
  };
}

/** A whole, positive number of hours. 72 by default: how long the newsletter has always told readers a link works. */
function confirmWindowHours(raw: unknown): number {
  if (raw === undefined) return 72;
  if (typeof raw !== "number" || !Number.isInteger(raw) || raw < 1) fail("confirmWindowHours must be a whole number of hours, at least 1");
  return raw;
}

function legacyNewsletterLinks(raw: unknown): boolean {
  if (raw === undefined) return false;
  if (typeof raw !== "boolean") fail("legacyNewsletterLinks must be true or false");
  return raw;
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
      consent: text(raw.consent, "consent", 500),
      confirmWindowHours: confirmWindowHours(raw.confirmWindowHours),
      itemUrlStyle: itemUrlStyle(raw.itemUrlStyle),
      configurationSet: matching(raw.configurationSet, "configurationSet", SES_NAME, "an SES configuration set name", `papyrus-${siteId}`),
      legacyNewsletterLinks: legacyNewsletterLinks(raw.legacyNewsletterLinks),
    };
  });
}
