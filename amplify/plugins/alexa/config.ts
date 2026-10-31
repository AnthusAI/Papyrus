import type { PluginRequest } from "../types";

/** The environment variable that carries the resolved config to the skill function. */
export const ALEXA_SETTINGS_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_SETTINGS";
const REQUEST_KEYS = [
  "name",
  "invocationName",
  "skillName",
  "skillId",
  "accountLinking",
  "siteOrigin",
  "siteId",
  "locales",
  "keywords",
  "iconSmallUri",
  "iconLargeUri",
  "privacyPolicyUrl",
  "termsOfUseUrl",
];
const SITE_ID = /^[a-z0-9][a-z0-9-]{0,62}$/;
/** Alexa locales a custom skill can be published in (the ones with a model we can generate unchanged). */
export const SKILL_LOCALES = ["en-US", "en-GB", "en-CA", "en-AU", "en-IN"] as const;
export const DEFAULT_SKILL_LOCALES: readonly string[] = ["en-US"];
/** Alexa's own rule for a custom skill's invocation name: lowercase letters, apostrophes, periods and spaces, 2 to 50 characters. */
export const INVOCATION_NAME = /^[a-z](?:[a-z' .]{0,48}[a-z.])$/;
export const SKILL_ID = /^amzn1\.ask\.skill\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HTTPS_ORIGIN = /^https:\/\/[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?$/;

/**
 * The resolved settings of the `alexa` plugin. Nothing here is secret: the whole object is passed to the skill function as
 * `PAPYRUS_ALEXA_SETTINGS` and read by the skill package generator.
 */
export type AlexaConfig = {
  /** What a person says after "Alexa, open". Required: there is no sensible default for a publication. */
  invocationName: string;
  /** The name the skill shows in the Alexa app. Defaults to the invocation name with each word capitalized. */
  skillName: string;
  /**
   * The skill ID (`amzn1.ask.skill.<uuid>`). It exists only after the skill has been created, so it is optional. When it is set,
   * the Lambda permission carries the skill ID event-source condition; the function itself refuses every request until it is set.
   */
  skillId?: string;
  /** Account linking is optional: the public parts of the skill work without it. */
  accountLinking: boolean;
  /** The site's public https origin, for the public story source and the manifest's icon and legal URLs. */
  siteOrigin?: string;
  /**
   * The site's id: names the skill's SSM parameters (`/papyrus/<siteId>/alexa/skill-id`). Defaults to the invocation name with
   * every run of other characters turned into one hyphen. The deploy-time sync and the function read the same resolved value.
   */
  siteId?: string;
  /** Locales to publish (default `["en-US"]`). Every locale gets the same generated model. */
  locales?: string[];
  /** Skill-store search keywords (default: the invocation name and "news"). */
  keywords?: string[];
  /** 108x108 PNG. Default `<siteOrigin>/alexa/icon-108.png`. */
  iconSmallUri?: string;
  /** 512x512 PNG. Default `<siteOrigin>/alexa/icon-512.png`. */
  iconLargeUri?: string;
  /** Default `<siteOrigin>/alexa/privacy`. */
  privacyPolicyUrl?: string;
  /** Default `<siteOrigin>/alexa/terms`. */
  termsOfUseUrl?: string;
};

/** The id that names the skill's SSM parameters. */
export function resolveSiteId(config: Pick<AlexaConfig, "invocationName" | "siteId">): string {
  return config.siteId ?? config.invocationName.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/** Where the sync stores, and the function reads, the skill ID. A plain String parameter: a skill ID is not secret. */
export function skillIdParameterName(config: Pick<AlexaConfig, "invocationName" | "siteId">): string {
  return `/papyrus/${resolveSiteId(config)}/alexa/skill-id`;
}

/** Where the sync keeps the hash of what it last pushed, so an unchanged deploy makes no Amazon call. */
export function contentHashParameterName(config: Pick<AlexaConfig, "invocationName" | "siteId">): string {
  return `/papyrus/${resolveSiteId(config)}/alexa/content-hash`;
}

function titleCase(value: string): string {
  return value
    .split(" ")
    .filter((word) => word.length > 0)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

export function resolveAlexaConfig(request: PluginRequest): AlexaConfig {
  const settings: Record<string, unknown> = typeof request === "string" ? {} : request;
  const unknown = Object.keys(settings).filter((key) => !REQUEST_KEYS.includes(key));
  if (unknown.length > 0) throw new Error(`Unknown alexa plugin settings: ${unknown.join(", ")}`);

  const invocationName = settings.invocationName;
  if (typeof invocationName !== "string" || !INVOCATION_NAME.test(invocationName)) {
    throw new Error(
      "alexa invocationName is required: 2 to 50 lowercase letters, apostrophes, periods and spaces (what a person says after \"Alexa, open\")",
    );
  }
  const skillName = settings.skillName ?? titleCase(invocationName);
  if (typeof skillName !== "string" || skillName.trim().length === 0 || skillName.length > 50) {
    throw new Error("alexa skillName must be a text of 1 to 50 characters");
  }
  const skillId = settings.skillId;
  if (skillId !== undefined && (typeof skillId !== "string" || !SKILL_ID.test(skillId))) {
    throw new Error("alexa skillId must look like amzn1.ask.skill.<uuid>");
  }
  const accountLinking = settings.accountLinking ?? false;
  if (typeof accountLinking !== "boolean") throw new Error("alexa accountLinking must be true or false");
  const siteOrigin = settings.siteOrigin;
  if (siteOrigin !== undefined && (typeof siteOrigin !== "string" || !HTTPS_ORIGIN.test(siteOrigin))) {
    throw new Error("alexa siteOrigin must be an https origin without a path, such as https://example.com");
  }
  const siteId = settings.siteId;
  if (siteId !== undefined && (typeof siteId !== "string" || !SITE_ID.test(siteId))) {
    throw new Error("alexa siteId must be lowercase letters, digits and hyphens (it names the skill's SSM parameters)");
  }
  const locales = settings.locales;
  if (
    locales !== undefined &&
    (!Array.isArray(locales) || locales.length === 0 || locales.some((locale) => !(SKILL_LOCALES as readonly string[]).includes(locale)) || new Set(locales).size !== locales.length)
  ) {
    throw new Error(`alexa locales must be a non-empty list without repeats from: ${SKILL_LOCALES.join(", ")}`);
  }
  const keywords = settings.keywords;
  if (keywords !== undefined && (!Array.isArray(keywords) || keywords.length === 0 || keywords.some((word) => typeof word !== "string" || word.trim() === ""))) {
    throw new Error("alexa keywords must be a non-empty list of words");
  }
  const urls: Record<string, string> = {};
  for (const key of ["iconSmallUri", "iconLargeUri", "privacyPolicyUrl", "termsOfUseUrl"]) {
    const value = settings[key];
    if (value === undefined) continue;
    if (typeof value !== "string" || !/^https:\/\/\S+$/.test(value)) throw new Error(`alexa ${key} must be an https URL`);
    urls[key] = value;
  }
  return {
    invocationName,
    skillName,
    ...(skillId === undefined ? {} : { skillId }),
    accountLinking,
    ...(siteOrigin === undefined ? {} : { siteOrigin }),
    ...(siteId === undefined ? {} : { siteId }),
    ...(locales === undefined ? {} : { locales: locales as string[] }),
    ...(keywords === undefined ? {} : { keywords: keywords as string[] }),
    ...urls,
  };
}
