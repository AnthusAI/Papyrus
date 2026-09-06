import type { EditionPresentationFormat } from "../../lib/content-types";

/**
 * Layout ("newsprint" | "blog" | "magazine") is Pretext-internal: it is the
 * look within Pretext, not a concept every renderer needs to share. This is
 * the canonical list of layouts the Pretext renderer actually supports,
 * consumed both by `renderers/pretext`'s `supportsLayout` and by
 * `lib/site-brand.ts`'s `getPresentationChoices` (today the only renderer,
 * so "layouts the app can choose from" and "layouts Pretext supports" are
 * the same list).
 */
export const PRETEXT_LAYOUTS: readonly EditionPresentationFormat[] = ["newsprint", "blog", "magazine"];

export function pretextSupportsLayout(layout: EditionPresentationFormat): boolean {
  return PRETEXT_LAYOUTS.includes(layout);
}
