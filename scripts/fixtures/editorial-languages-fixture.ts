/**
 * An in-memory stand-in for the editorial checks door (lib/editorial-checks-client.ts) for the Administration > Editorial checks browser acceptance. It holds the stored
 * settings, records every save, and answers `describeLanguages` the way the server's one validation would for the inputs the scenarios use: the rules themselves are
 * checked in features_backend/translation/editorial-languages-setting.feature, not here. Nothing leaves the page.
 */
import { DEFAULT_EDITORIAL_SETTINGS, mergeEditorialSettings, type EditorialSettings } from "../../lib/editorial-checks-settings";
import type { LanguagesDescription } from "../../lib/editorial-languages-form";

export { DEFAULT_EDITORIAL_SETTINGS };
export type { EditorialSettings };

type Languages = EditorialSettings["languages"];
const STORED: Record<string, Record<string, unknown>> = {
  plain: { guidance: "Plain words.", languages: { primary: "en", enabled: ["en", "es-419", "zh-Hans"], futureKey: { kept: true } } },
  configured: {
    guidance: "Plain words.",
    languages: {
      primary: "en", enabled: ["en", "es-419", "zh-Hans"], public: ["en", "es-419"], prefixes: { "es-419": "latam" }, slugs: { "zh-Hans": "pinyin" }, futureKey: { kept: true },
    },
  },
};

const base = (tag: string) => tag.split("-")[0].toLowerCase();
const REFUSAL = "languages.prefixes: es-419 and zh-Hans would both be served under /zh/.";

const params = new URLSearchParams(location.search);
const scenario = params.get("scenario") || "plain";
export const calls: { op: string; input: any }[] = [];
(window as any).fixtureBackend = { calls };

/** What the server answers for a setting the scenarios hold: the effective and default values of each enabled language, or the refusal named in the scenario. */
export async function describeLanguages(languages: Languages): Promise<LanguagesDescription> {
  calls.push({ op: "describeLanguages", input: languages });
  if (languages.prefixes?.["es-419"] === "zh") return { ok: false, message: REFUSAL };
  return {
    ok: true,
    primary: languages.primary,
    enabled: languages.enabled,
    languages: languages.enabled.map((tag) => {
      const primary = tag === languages.primary;
      const chinese = tag.startsWith("zh");
      return {
        tag, primary, public: primary || (languages.public ?? []).includes(tag),
        prefix: primary ? "" : languages.prefixes?.[tag] ?? base(tag), defaultPrefix: primary ? "" : base(tag),
        slugPolicy: primary ? null : languages.slugs?.[tag] ?? (chinese ? "characters" : "translated"), defaultSlugPolicy: primary ? null : chinese ? "characters" : "translated",
      };
    }),
  };
}

export async function loadSettings() {
  return { settings: mergeEditorialSettings(STORED[scenario] as never), exists: true };
}

export async function saveSettings(settings: EditorialSettings, exists: boolean) {
  calls.push({ op: "saveSettings", input: { settings: JSON.parse(JSON.stringify(settings)), exists } });
}

export async function listPolicies() { return []; }
export async function listStarterPacks() { return { packs: [] }; }
const refuse = async () => { throw new Error("The fixture has no such door."); };
export const deletePolicy = refuse, draftQuestions = refuse, importStarterPack = refuse, recalibrate = refuse, savePolicy = refuse, tryPolicy = refuse;
