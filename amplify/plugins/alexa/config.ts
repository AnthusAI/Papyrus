import type { PluginRequest } from "../types";

/** The environment variable that carries the resolved config to the skill function. */
export const ALEXA_SETTINGS_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_SETTINGS";
const REQUEST_KEYS = ["name", "invocationName", "skillName", "skillId", "accountLinking", "siteOrigin"];
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
  /** The site's public https origin, for the public story source. */
  siteOrigin?: string;
};

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
  return {
    invocationName,
    skillName,
    ...(skillId === undefined ? {} : { skillId }),
    accountLinking,
    ...(siteOrigin === undefined ? {} : { siteOrigin }),
  };
}
