/** Runtime settings for editorial checks, stored in EditorialCheckSettings (id "settings"). */
export type EditorialSettings = {
  /** Core to every site and on by default; a publication turns its checks off here. */
  enabled: boolean;
  lanes: { rules: boolean; classifier: boolean };
  classifierModel: string;
  rewriteModel: string;
  deadlineSeconds: number;
  maxInputTokens: number;
  maxExamplesPerQuestion: number;
  guidance: string;
  publishWarning: boolean;
  /** Checks run on their own after the body changes and after each save. On unless an admin sets this to false (absent or null counts as on). */
  checkWhileTyping: boolean;
  /**
   * The languages the site writes in (PPY-d0132d): `primary`, the language Stories are first written in, and `enabled`, every language the site
   * publishes, the primary included. Each tag names the exact variant (neutral Latin American Spanish is `es-419`). Enabling a language brings its
   * starter policies on the next deploy.
   *
   * How they are served (src/papyrus_content/language_serving.py, docs/multilingual-serving.md): `prefixes` (each non-primary language's URL prefix;
   * default its base subtag, es-419 -> es), `public` (the languages the public site serves; default only the primary) and `slugs` (each language's
   * slug policy: translated, characters, pinyin or primary; default characters for Chinese, translated otherwise). Saving keeps them as stored.
   */
  languages: { primary: string; enabled: string[]; prefixes?: Record<string, string>; public?: string[]; slugs?: Record<string, string> };
};

export const DEFAULT_EDITORIAL_SETTINGS: EditorialSettings = {
  enabled: true,
  lanes: { rules: true, classifier: true },
  classifierModel: "jev-latest",
  rewriteModel: "gpt-6-luna",
  deadlineSeconds: 20,
  maxInputTokens: 500000,
  maxExamplesPerQuestion: 4,
  guidance: "",
  publishWarning: true,
  checkWhileTyping: true,
  languages: { primary: "en", enabled: ["en"] },
};

/**
 * The language a Story is written in. Every Story is written in the site's primary language until Stories carry their own language
 * (the multilingual plan's Item.language); this mirrors `story_language` in src/papyrus_content/editorial_languages.py.
 */
export function storyLanguage(settings: Pick<EditorialSettings, "languages">): string {
  return settings.languages.primary;
}

/**
 * Stored settings over the defaults. A stored `null` (or a missing key) never overrides a default, so a record that
 * predates a setting, or holds null for it, behaves like the default: checks run automatically.
 */
export function mergeEditorialSettings(stored: Partial<{ [K in keyof EditorialSettings]: EditorialSettings[K] | null }> | null | undefined): EditorialSettings {
  const merged: Record<string, unknown> = { ...DEFAULT_EDITORIAL_SETTINGS };
  for (const [name, value] of Object.entries(stored ?? {})) if (value !== null && value !== undefined) merged[name] = value;
  merged.lanes = { ...DEFAULT_EDITORIAL_SETTINGS.lanes, ...(stored?.lanes ?? {}) };
  return merged as EditorialSettings;
}
