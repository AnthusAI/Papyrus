export type SiteEnv = "production" | "staging" | "development";
export type ContentSource = "published" | "drafts";

type EnvironmentVariables = Record<string, string | undefined>;

const SITE_ENVIRONMENTS: readonly SiteEnv[] = ["production", "staging", "development"];
const CONTENT_SOURCES: readonly ContentSource[] = ["published", "drafts"];
const PRODUCTION_BRANCH = "main";

export function getSiteEnv(environment: EnvironmentVariables = process.env): SiteEnv {
  const configured = (environment.SITE_ENV ?? "").trim();
  if (!configured) return "development";
  if (!SITE_ENVIRONMENTS.includes(configured as SiteEnv)) {
    throw new Error(`SITE_ENV must be one of ${SITE_ENVIRONMENTS.join(", ")}; received "${configured}".`);
  }
  if (configured === "production") {
    const branch = (environment.AWS_BRANCH ?? "").trim();
    if (branch && branch !== PRODUCTION_BRANCH) return "staging";
  }
  return configured as SiteEnv;
}

export function getContentSource(environment: EnvironmentVariables = process.env): ContentSource {
  const configured = (environment.PAPYRUS_CONTENT_SOURCE ?? "").trim();
  if (!configured) return "published";
  if (!CONTENT_SOURCES.includes(configured as ContentSource)) {
    throw new Error(`PAPYRUS_CONTENT_SOURCE must be one of ${CONTENT_SOURCES.join(", ")}; received "${configured}".`);
  }
  return configured as ContentSource;
}

export function isIndexable(environment: EnvironmentVariables = process.env): boolean {
  return getSiteEnv(environment) === "production";
}

export function showStagingBanner(environment: EnvironmentVariables = process.env): boolean {
  return getSiteEnv(environment) === "staging";
}

export function analyticsAllowed(environment: EnvironmentVariables = process.env): boolean {
  return getSiteEnv(environment) === "production";
}

export function assertContentSourceMatchesEnv(environment: EnvironmentVariables = process.env): void {
  if (getContentSource(environment) !== "drafts") return;
  const siteEnv = getSiteEnv(environment);
  if (siteEnv !== "staging") {
    throw new Error(
      `PAPYRUS_CONTENT_SOURCE=drafts requires SITE_ENV=staging; the resolved site environment is "${siteEnv}". Drafts must never be served from production or development.`,
    );
  }
}
