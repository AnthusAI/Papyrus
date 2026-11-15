"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { describeLanguages } from "../lib/editorial-checks-client";
import {
  SLUG_POLICIES,
  SLUG_POLICY_LABELS,
  checkAfter,
  setPrefix,
  setPublic,
  setSlugPolicy,
  settleLanguages,
  type LanguagesCheck,
  type SiteLanguages,
} from "../lib/editorial-languages-form";

/**
 * The languages setting, checked by the server as it is edited (the rules are `serving_languages` in src/papyrus_content/language_serving.py; this form holds
 * none of them). `check` is `checking` from the first change until the answer arrives, so a save waits for it.
 */
export function useLanguagesCheck(languages: SiteLanguages): LanguagesCheck {
  const [check, setCheck] = useState<LanguagesCheck>({ status: "checking", rows: [] });
  const key = JSON.stringify(settleLanguages(languages));
  useEffect(() => {
    let current = true;
    setCheck((last) => ({ status: "checking", rows: last.rows }));
    const timer = setTimeout(() => {
      describeLanguages(JSON.parse(key) as SiteLanguages)
        .then((description) => current && setCheck((last) => checkAfter(last, description)))
        .catch((error: unknown) => current && setCheck((last) => ({ status: "refused", rows: last.rows, message: `Could not check the languages: ${error instanceof Error ? error.message : String(error)}` })));
    }, 300);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [key]);
  return check;
}

type Props = { languages: SiteLanguages; check: LanguagesCheck; onChange: (languages: SiteLanguages) => void };

/** Which enabled languages are public, each one's URL prefix and slug policy. The primary language is the site's root and always public. */
export function EditorialLanguagesControls({ languages, check, onChange }: Props) {
  const others = check.rows.filter((row) => !row.primary);
  return (
    <fieldset className="min-w-0 space-y-2" data-editorial-languages>
      <legend>How the site serves its languages</legend>
      <p className="text-sm text-muted-foreground">
        An enabled language that is not public is written, translated and checked, but gets no page on the public site. The primary language is always public.
      </p>
      <p aria-live="polite" data-editorial-languages-status role="status">
        {check.status === "refused" ? <span data-editorial-languages-refusal>{check.message}</span> : check.status === "checking" ? "Checking the languages…" : null}
      </p>
      {others.length === 0 && check.status === "ok" ? <p className="text-sm text-muted-foreground">Add a second language above to choose how it is served.</p> : null}
      {others.map((row) => (
        <div className="grid min-w-0 gap-3 rounded-md bg-muted/40 p-3 md:grid-cols-3" data-editorial-language={row.tag} key={row.tag}>
          <strong className="md:col-span-3">{row.tag}</strong>
          <label className="flex min-w-0 items-start gap-2">
            <input
              checked={(languages.public ?? []).includes(row.tag)}
              data-language-public
              onChange={(event) => onChange(setPublic(languages, row.tag, event.target.checked))}
              type="checkbox"
            />
            Public: readers can visit its pages
          </label>
          <label className="flex min-w-0 flex-col gap-1">
            <span>Web address prefix (default {row.defaultPrefix})</span>
            <Input
              data-language-prefix
              onChange={(event) => onChange(setPrefix(languages, row.tag, event.target.value))}
              placeholder={row.defaultPrefix}
              value={languages.prefixes?.[row.tag] ?? ""}
            />
            <small className="text-muted-foreground">Its pages live under /{languages.prefixes?.[row.tag]?.trim() || row.defaultPrefix}/</small>
          </label>
          <label className="flex min-w-0 flex-col gap-1">
            <span>Page addresses (slugs)</span>
            <select
              className="w-full min-w-0"
              data-language-slug
              onChange={(event) => onChange(setSlugPolicy(languages, row.tag, event.target.value))}
              value={languages.slugs?.[row.tag] ?? ""}
            >
              <option value="">Default ({row.defaultSlugPolicy ? SLUG_POLICY_LABELS[row.defaultSlugPolicy].toLowerCase() : "translated"})</option>
              {SLUG_POLICIES.map((policy) => (
                <option key={policy} value={policy}>{SLUG_POLICY_LABELS[policy]}</option>
              ))}
            </select>
            <small className="text-muted-foreground">How a translation&apos;s address is first made; it never changes after the first publish.</small>
          </label>
        </div>
      ))}
    </fieldset>
  );
}
