import type { PluginRequest } from "../types";

/** The environment variable that carries the resolved config to the skill function. */
export const ALEXA_SETTINGS_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_SETTINGS";
const REQUEST_KEYS = ["name", "invocationName", "skillName", "skillId", "accountLinking", "amazonVendorId", "siteOrigin", "theme"];
/** Alexa's own rule for a custom skill's invocation name: lowercase letters, apostrophes, periods and spaces, 2 to 50 characters. */
export const INVOCATION_NAME = /^[a-z](?:[a-z' .]{0,48}[a-z.])$/;
export const SKILL_ID = /^amzn1\.ask\.skill\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** The vendor ID of the Amazon developer account that owns the skill (uppercase letters and digits), from the developer console. */
export const AMAZON_VENDOR_ID = /^[A-Z0-9]{10,40}$/;
const HTTPS_ORIGIN = /^https:\/\/[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?$/;

/**
 * The resolved settings of the `alexa` plugin. Nothing here is secret: the whole object is passed to the skill function as
 * `PAPYRUS_ALEXA_SETTINGS` and read by the skill package generator.
 */
export type AlexaTheme = {
  /** The screen background. */
  background: string;
  /** Cards and panels, one step off the background. */
  surface: string;
  /** Headlines and body text. */
  text: string;
  /** Decks, bylines and dates. */
  mutedText: string;
  /** Publication name and small marks. */
  accent: string;
};

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
  /** The skill owner's Amazon vendor ID. Required when `accountLinking` is on: it names Amazon's account-linking redirect URLs. */
  amazonVendorId?: string;
  /** The site's public https origin, for the public story source. */
  siteOrigin?: string;
  /** Colours for the on-screen (APL) documents, as #rrggbb. Absent: the APL documents use their built-in dark brand theme. */
  theme?: AlexaTheme;
};

function titleCase(value: string): string {
  return value
    .split(" ")
    .filter((word) => word.length > 0)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

const THEME_KEYS = ["background", "surface", "text", "mutedText", "accent"] as const;
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
/** WCAG AA for body text. */
const MINIMUM_TEXT_CONTRAST = 4.5;

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5].map((start) => {
    const channel = parseInt(hex.slice(start, start + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The WCAG contrast ratio of two #rrggbb colours (1 to 21). */
export function contrastRatio(first: string, second: string): number {
  const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

function resolveTheme(value: unknown): AlexaTheme {
  const fail = (message: string): never => {
    throw new Error(`alexa theme ${message}`);
  };
  if (typeof value !== "object" || value === null || Array.isArray(value)) return fail("must be an object with background, surface, text, mutedText and accent");
  const entries = value as Record<string, unknown>;
  const unknown = Object.keys(entries).filter((key) => !(THEME_KEYS as readonly string[]).includes(key));
  if (unknown.length > 0) return fail(`has unknown colours: ${unknown.join(", ")}`);
  for (const key of THEME_KEYS) {
    if (typeof entries[key] !== "string" || !HEX_COLOR.test(entries[key] as string)) return fail(`${key} must be a colour like #1a2b3c`);
  }
  const theme = Object.fromEntries(THEME_KEYS.map((key) => [key, (entries[key] as string).toLowerCase()])) as AlexaTheme;
  for (const ground of [theme.background, theme.surface]) {
    for (const ink of [theme.text, theme.mutedText]) {
      if (contrastRatio(ink, ground) < MINIMUM_TEXT_CONTRAST) return fail(`needs a contrast ratio of at least ${MINIMUM_TEXT_CONTRAST} between ${ink} and ${ground}`);
    }
  }
  return theme;
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
  const amazonVendorId = settings.amazonVendorId;
  if (amazonVendorId !== undefined && (typeof amazonVendorId !== "string" || !AMAZON_VENDOR_ID.test(amazonVendorId))) {
    throw new Error("alexa amazonVendorId must be uppercase letters and digits, as the developer console shows it");
  }
  if (accountLinking && amazonVendorId === undefined) throw new Error("alexa amazonVendorId is required when accountLinking is true");
  const siteOrigin = settings.siteOrigin;
  if (siteOrigin !== undefined && (typeof siteOrigin !== "string" || !HTTPS_ORIGIN.test(siteOrigin))) {
    throw new Error("alexa siteOrigin must be an https origin without a path, such as https://example.com");
  }
  return {
    invocationName,
    skillName,
    ...(skillId === undefined ? {} : { skillId }),
    accountLinking,
    ...(amazonVendorId === undefined ? {} : { amazonVendorId }),
    ...(siteOrigin === undefined ? {} : { siteOrigin }),
    ...(settings.theme === undefined ? {} : { theme: resolveTheme(settings.theme) }),
  };
}
