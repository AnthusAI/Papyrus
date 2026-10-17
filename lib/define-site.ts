import type { PapyrusSiteBackendConfig } from "../amplify/site-backend-config";
import type { SiteBrand } from "./site-brand";

/**
 * What a publication repo's `papyrus.config.ts` default-exports.
 * Resolved by the `papyrus-site` alias (tsconfig `paths` in Papyrus itself,
 * `withPapyrus()` in a publication repo). Also the argument of
 * `defineSiteBackend(site)` so `ampx` never needs the brand graph.
 */
export type PapyrusSite = {
  /** Brands this publication registers (in addition to Papyrus's built-ins). */
  brands?: SiteBrand[];
  /** Brand used when PAPYRUS_SITE_BRAND is unset. */
  defaultBrand?: string;
  /** Options for `defineSiteBackend(site)` (Amplify Gen 2 backend). */
  backend?: PapyrusSiteBackendConfig;
};

export function defineSite(site: PapyrusSite): PapyrusSite {
  return site;
}
