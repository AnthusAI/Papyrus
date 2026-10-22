import type { PluginRequest } from "../types";

export const NEWSLETTER_SITE_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
export const NEWSLETTER_LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;
export const COMPUTE_ROLE_ARN = /^arn:aws:iam::[0-9]{12}:role\/[A-Za-z0-9+=,.@_/-]{1,512}$/;
const HOSTNAME = /^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
const LOCAL_PART = /^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
const SES_NAME = /^[A-Za-z0-9_-]{1,64}$/;
const ISSUE_TYPE = /^[a-z][a-z0-9_]{0,59}$/;
/** One path segment: it is the Item section of the archive and the `urls.sections` key of the site's projection.json. */
const ARCHIVE_PATH = /^\/[a-z0-9][a-z0-9_-]*\/$/;
const SCHEDULER_CRON = /^cron\(\S+ \S+ \S+ \S+ \S+ \S+\)$/;
const UNSAFE_CSS = /[<>{};"\\`]|url\(|expression\(|@import/i;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

export const ITEM_URL_STYLES = ["html", "directory", "clean"] as const;
export type ItemUrlStyle = (typeof ITEM_URL_STYLES)[number];

export type NewsletterTheme = {
  accent: string;
  text: string;
  background: string;
  surface?: string;
  muted?: string;
  fontFamily?: string;
  logoUrl?: string;
};

export type NewsletterRule = { sections?: string[]; tags?: string[]; types?: string[] };

type ListBase = { id: string; name: string; description: string };
export type RoundupList = ListBase & {
  kind: "roundup";
  /** EventBridge Scheduler cron for assembling the draft, and the IANA time zone it runs in. */
  schedule: { draft: string; timezone: string };
  /** The CMS item type of an issue. */
  issueType: string;
  /** Where the sent issue is archived, such as `/roundup/`: one path segment, also the section the issue Items are filed under. */
  archivePath: string;
};
export type AlertList = ListBase & {
  kind: "alert";
  /** Which published items raise an alert. Absent or empty: every published item (an admin still approves it). */
  rule: NewsletterRule;
  approval: "admin" | "none";
};
export type NewsletterList = RoundupList | AlertList;

export type NewsletterConfig = {
  /** The site id: names the key parameter, the configuration set and the event topic. Must match the sending stack's SiteId. */
  siteId: string;
  /** The site's public https origin: confirmation links point at `<siteOrigin>/api/newsletter/confirm`. */
  siteOrigin: string;
  /** The IAM role of the CMS app's server runtime (the `CmsComputeRoleArn` output of the app-shell stack): the only caller of the function. */
  computeRoleArn: string;
  sendingDomain: string;
  fromAddress: string;
  fromName: string;
  /** A site must set this to true before any list may send without approval. */
  instantAlerts: boolean;
  theme: NewsletterTheme;
  lists: NewsletterList[];
  /** How the site addresses its item pages (`urls.style` in projection.json): roundup drafts link to published items with it. */
  itemUrlStyle: ItemUrlStyle;
  /** `papyrus-<siteId>` unless overridden. */
  configurationSet: string;
  /** `papyrus-newsletter-events-<siteId>` unless overridden. */
  eventTopicName: string;
};

const KNOWN_KEYS = new Set([
  "name", "siteId", "siteOrigin", "computeRoleArn", "sendingDomain", "fromAddress", "fromName", "instantAlerts", "theme", "lists",
  "configurationSet", "eventTopicName", "itemUrlStyle",
]);
const LIST_KEYS = {
  roundup: ["id", "name", "description", "kind", "schedule", "issueType", "archivePath"],
  alert: ["id", "name", "description", "kind", "rule", "approval"],
};

function fail(message: string): never {
  throw new Error(`newsletter plugin ${message}`);
}

function record(raw: unknown, label: string, known: string[]): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) fail(`${label} must be an object`);
  const unknown = Object.keys(raw).filter((key) => !known.includes(key));
  if (unknown.length > 0) fail(`${label} has unknown settings: ${unknown.join(", ")}`);
  return raw as Record<string, unknown>;
}

function text(raw: unknown, label: string, maximum: number, options: { optional?: boolean; fallback?: string } = {}): string {
  const value = raw === undefined ? options.fallback : raw;
  if (value === undefined) fail(`${label} is required`);
  if (typeof value !== "string" || CONTROL_CHARACTERS.test(value) || value.trim() !== value) {
    fail(`${label} must be text on one line with no leading or trailing spaces`);
  }
  if (value.length === 0 && !options.optional) fail(`${label} is required`);
  if (value.length > maximum) fail(`${label} must be at most ${maximum} characters`);
  return value;
}

function matching(raw: unknown, label: string, pattern: RegExp, description: string, fallback?: string): string {
  const value = raw === undefined ? fallback : raw;
  if (typeof value !== "string" || !pattern.test(value)) fail(`${label} must be ${description}`);
  return value;
}

function timeZone(raw: unknown, label: string): string {
  const value = text(raw, label, 64);
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: value });
  } catch {
    fail(`${label} must be an IANA time zone such as America/New_York`);
  }
  return value;
}

function origin(raw: unknown): string {
  const value = text(raw, "siteOrigin", 200);
  let parsed: URL | undefined;
  try {
    parsed = new URL(value);
  } catch {
    parsed = undefined;
  }
  if (!parsed || parsed.protocol !== "https:" || parsed.origin !== value) fail("siteOrigin must be an https origin such as https://example.com with no path");
  return value;
}

function stringList(raw: unknown, label: string): string[] | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > 50) fail(`${label} must be a list of 1 to 50 names`);
  return [...new Set(raw.map((entry, index) => text(entry, `${label}[${index}]`, 80)))];
}

function itemUrlStyle(raw: unknown): ItemUrlStyle {
  if (raw === undefined) return "html";
  if (typeof raw !== "string" || !(ITEM_URL_STYLES as readonly string[]).includes(raw)) fail(`itemUrlStyle must be one of ${ITEM_URL_STYLES.join(", ")}`);
  return raw as ItemUrlStyle;
}

function resolveTheme(raw: unknown): NewsletterTheme {
  const theme = record(raw, "theme", ["accent", "text", "background", "surface", "muted", "fontFamily", "logoUrl"]);
  const resolved: NewsletterTheme = {
    accent: text(theme.accent, "theme.accent", 80),
    text: text(theme.text, "theme.text", 80),
    background: text(theme.background, "theme.background", 80),
  };
  for (const key of ["surface", "muted", "fontFamily"] as const) {
    if (theme[key] !== undefined) resolved[key] = text(theme[key], `theme.${key}`, 200);
  }
  for (const [key, value] of Object.entries(resolved)) {
    if (UNSAFE_CSS.test(value)) fail(`theme.${key} contains characters that are not allowed in a style value`);
  }
  if (theme.logoUrl !== undefined) {
    const logoUrl = text(theme.logoUrl, "theme.logoUrl", 500);
    if (!/^https:\/\//.test(logoUrl)) fail("theme.logoUrl must be an https URL");
    resolved.logoUrl = logoUrl;
  }
  return resolved;
}

function resolveRule(raw: unknown, label: string): NewsletterRule {
  if (raw === undefined) return {};
  const rule = record(raw, label, ["sections", "tags", "types"]);
  return {
    ...(rule.sections === undefined ? {} : { sections: stringList(rule.sections, `${label}.sections`) }),
    ...(rule.tags === undefined ? {} : { tags: stringList(rule.tags, `${label}.tags`) }),
    ...(rule.types === undefined ? {} : { types: stringList(rule.types, `${label}.types`) }),
  };
}

function resolveList(raw: unknown, index: number, instantAlerts: boolean): NewsletterList {
  const label = `lists[${index}]`;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) fail(`${label} must be an object`);
  const kind = (raw as Record<string, unknown>).kind;
  if (kind !== "roundup" && kind !== "alert") fail(`${label}.kind must be "roundup" or "alert"`);
  const list = record(raw, label, LIST_KEYS[kind]);
  const base = {
    id: matching(list.id, `${label}.id`, NEWSLETTER_LIST_ID, "lowercase letters, digits and hyphens, starting with a letter (at most 40 characters)"),
    name: text(list.name, `${label}.name`, 80),
    description: text(list.description, `${label}.description`, 300, { optional: true, fallback: "" }),
  };
  if (kind === "roundup") {
    const schedule = record(list.schedule, `${label}.schedule`, ["draft", "timezone"]);
    return {
      ...base,
      kind,
      schedule: {
        draft: matching(schedule.draft, `${label}.schedule.draft`, SCHEDULER_CRON, 'an EventBridge Scheduler cron such as "cron(0 13 ? * FRI *)"'),
        timezone: timeZone(schedule.timezone, `${label}.schedule.timezone`),
      },
      issueType: matching(list.issueType, `${label}.issueType`, ISSUE_TYPE, "a lowercase item type name", "newsletter_issue"),
      archivePath: matching(list.archivePath, `${label}.archivePath`, ARCHIVE_PATH, 'a path that starts and ends with "/", such as /roundup/'),
    };
  }
  const approval = list.approval === undefined ? "admin" : list.approval;
  if (approval !== "admin" && approval !== "none") fail(`${label}.approval must be "admin" or "none"`);
  if (approval === "none" && !instantAlerts) {
    fail(`${label}.approval "none" sends alerts without an admin approving them: set instantAlerts: true on the plugin first`);
  }
  return { ...base, kind, rule: resolveRule(list.rule, `${label}.rule`), approval };
}

export function resolveNewsletterConfig(request: PluginRequest): NewsletterConfig {
  const raw = record(typeof request === "string" ? { name: request } : request, "settings", [...KNOWN_KEYS]);
  const siteId = matching(raw.siteId, "siteId", NEWSLETTER_SITE_ID, "a lowercase site id (letters, digits, hyphens), the SiteId of the sending stack");
  const computeRoleArn = raw.computeRoleArn;
  if (typeof computeRoleArn !== "string" || !COMPUTE_ROLE_ARN.test(computeRoleArn)) {
    fail("computeRoleArn must be the IAM role ARN of the CMS app's compute role (the CmsComputeRoleArn output)");
  }
  const sendingDomain = matching(raw.sendingDomain, "sendingDomain", HOSTNAME, "a lowercase domain name such as news.example.com");
  const fromAddress = text(raw.fromAddress, "fromAddress", 254);
  const [local, domain, ...extra] = fromAddress.split("@");
  if (extra.length > 0 || !local || local.length > 64 || !LOCAL_PART.test(local) || domain !== sendingDomain) {
    fail(`fromAddress must be an address on ${sendingDomain} (lowercase, such as newsletter@${sendingDomain})`);
  }
  if (raw.instantAlerts !== undefined && typeof raw.instantAlerts !== "boolean") fail("instantAlerts must be a boolean");
  const instantAlerts = raw.instantAlerts === true;
  if (!Array.isArray(raw.lists) || raw.lists.length === 0 || raw.lists.length > 20) fail("lists must be a list of 1 to 20 lists");
  const lists = raw.lists.map((entry, index) => resolveList(entry, index, instantAlerts));
  const duplicates = lists.map((list) => list.id).filter((id, index, ids) => ids.indexOf(id) !== index);
  if (duplicates.length > 0) fail(`lists has duplicate ids: ${[...new Set(duplicates)].join(", ")}`);
  const roundups = lists.filter((list) => list.kind === "roundup");
  if (new Set(roundups.map((list) => (list as RoundupList).archivePath)).size !== roundups.length) fail("roundup lists need different archivePath values");
  return {
    siteId,
    siteOrigin: origin(raw.siteOrigin),
    computeRoleArn,
    sendingDomain,
    fromAddress,
    fromName: text(raw.fromName, "fromName", 80),
    instantAlerts,
    theme: resolveTheme(raw.theme),
    lists,
    itemUrlStyle: itemUrlStyle(raw.itemUrlStyle),
    configurationSet: matching(raw.configurationSet, "configurationSet", SES_NAME, "an SES configuration set name", `papyrus-${siteId}`),
    eventTopicName: matching(raw.eventTopicName, "eventTopicName", SES_NAME, "an SNS topic name", `papyrus-newsletter-events-${siteId}`),
  };
}
