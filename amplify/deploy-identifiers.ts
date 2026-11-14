/**
 * AWS identifiers a site backend needs (the CMS compute role, an existing edge distribution) without a site
 * repository having to carry them. Each has an environment variable that, when set, wins over the value written
 * in the site's backend configuration; the written value stays a working fallback so existing sites keep
 * deploying until they migrate. The variables are set on the Amplify branch (docs/site-hosting.md#aws-identifiers-outside-git);
 * `PAPYRUS_COMPUTE_ROLE_ARN` is set by the app-shell stack itself. They are read at backend build time only and
 * never reach a browser bundle.
 */
export const COMPUTE_ROLE_ARN_ENVIRONMENT_VARIABLE = "PAPYRUS_COMPUTE_ROLE_ARN";
export const EDGE_DISTRIBUTION_ARN_ENVIRONMENT_VARIABLE = "PAPYRUS_EDGE_DISTRIBUTION_ARN";

export type IdentifierEnvironment = Record<string, string | undefined>;

/** The environment value when it is set and not blank, otherwise the configured value (which may be undefined). */
export function environmentOrConfigured<T>(
  name: string,
  configured: T | undefined,
  environment: IdentifierEnvironment = process.env,
): string | T | undefined {
  const fromEnvironment = environment[name]?.trim();
  return fromEnvironment ? fromEnvironment : configured;
}
