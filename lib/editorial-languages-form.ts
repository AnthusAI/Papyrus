/**
 * The editing side of the `languages` editorial setting (Administration > Editorial checks): which enabled languages are public, each language's URL
 * prefix and each language's slug policy. The rules those keys must obey are not here. They live in one place, `serving_languages` in
 * src/papyrus_content/language_serving.py, and the form asks the `describeEditorialLanguages` query, which runs them (docs/multilingual-serving.md).
 *
 * Every function returns a new object that keeps every key it was not asked to change, so a save never drops a key the form does not show.
 */
import type { EditorialSettings } from "./editorial-checks-settings";

export type SiteLanguages = EditorialSettings["languages"];

export const SLUG_POLICIES = ["translated", "characters", "pinyin", "primary"] as const;

export const SLUG_POLICY_LABELS: Record<string, string> = {
  translated: "Translated title, in plain letters",
  characters: "Title in its own script (Chinese characters kept)",
  pinyin: "Pinyin (Chinese written in Latin letters)",
  primary: "Same as the original story's address",
};

/** One enabled language as the server describes it: its effective values and the defaults it would otherwise get. */
export type LanguageRow = {
  tag: string;
  primary: boolean;
  public: boolean;
  prefix: string;
  defaultPrefix: string;
  slugPolicy: string | null;
  defaultSlugPolicy: string | null;
};

/** Where the check of the setting stands. `rows` are the last language list the server described, kept while a new check runs or refuses so the fields stay editable. */
export type LanguagesCheck = { status: "checking" | "ok" | "refused"; rows: LanguageRow[]; message?: string };

export type LanguagesDescription = { ok: true; primary: string; enabled: string[]; languages: LanguageRow[] } | { ok: false; message: string };

/** `edited` without the entries of a key that name a language no longer enabled (or the primary, which has no prefix or slug policy). */
function without<T>(entries: Record<string, T> | undefined, keep: (tag: string) => boolean): Record<string, T> | undefined {
  if (!entries) return undefined;
  const kept = Object.fromEntries(Object.entries(entries).filter(([tag]) => keep(tag)));
  return Object.keys(kept).length > 0 ? kept : undefined;
}

function setKey<K extends keyof SiteLanguages>(languages: SiteLanguages, key: K, value: SiteLanguages[K] | undefined): SiteLanguages {
  const { [key]: _removed, ...rest } = languages;
  return (value === undefined ? rest : { ...rest, [key]: value }) as SiteLanguages;
}

/**
 * The setting as it is saved and checked: entries for a language the site no longer writes in are dropped (taking a language out of the list takes its
 * public flag, prefix and slug policy with it), and a public list always starts with the primary. Left as typed while the list is being edited, so
 * retyping a language does not lose its settings.
 */
export function settleLanguages(languages: SiteLanguages): SiteLanguages {
  const others = (tag: string) => languages.enabled.includes(tag) && tag !== languages.primary;
  let settled = setKey(languages, "prefixes", without(languages.prefixes, others));
  settled = setKey(settled, "slugs", without(languages.slugs, others));
  if (languages.public === undefined) return settled;
  const listed = languages.public.filter((tag) => others(tag));
  return setKey(settled, "public", listed.length > 0 ? [languages.primary, ...listed] : undefined);
}

/** Make one non-primary language public or not. Nothing public beyond the primary is no list at all (the default). */
export function setPublic(languages: SiteLanguages, tag: string, on: boolean): SiteLanguages {
  const current = (languages.public ?? []).filter((listed) => listed !== languages.primary && listed !== tag);
  const next = on ? [...current, tag] : current;
  return setKey(languages, "public", next.length > 0 ? [languages.primary, ...next] : undefined);
}

/** Set one language's URL prefix; blank returns it to the default. */
export function setPrefix(languages: SiteLanguages, tag: string, prefix: string): SiteLanguages {
  const { [tag]: _old, ...others } = languages.prefixes ?? {};
  const next = prefix.trim() === "" ? others : { ...others, [tag]: prefix.trim() };
  return setKey(languages, "prefixes", Object.keys(next).length > 0 ? next : undefined);
}

/** Set one language's slug policy; blank returns it to the default. */
export function setSlugPolicy(languages: SiteLanguages, tag: string, policy: string): SiteLanguages {
  const { [tag]: _old, ...others } = languages.slugs ?? {};
  const next = policy === "" ? others : { ...others, [tag]: policy };
  return setKey(languages, "slugs", Object.keys(next).length > 0 ? next : undefined);
}

/** The check after the server's answer: refused keeps the rows of the last answer that was fine, so the fields that caused it can be corrected. */
export function checkAfter(last: LanguagesCheck, description: LanguagesDescription): LanguagesCheck {
  return description.ok
    ? { status: "ok", rows: description.languages }
    : { status: "refused", rows: last.rows, message: description.message };
}
