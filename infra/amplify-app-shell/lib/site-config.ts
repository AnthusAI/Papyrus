import { parseCloudEmail, type CloudEmailConfig } from "./cloud-email-config";

export type CmsRedirect = {
  source: string;
  status: 301 | 302;
};

export type ReaderRedirectStatus = "301" | "302" | "200" | "404" | "404-200";

export type ReaderRedirect = {
  source: string;
  target: string;
  status: ReaderRedirectStatus;
};

export type ReaderCustomHeaderRule = {
  pattern: string;
  headers: Record<string, string>;
};

export const READER_REDIRECT_STATUSES: ReaderRedirectStatus[] = ["301", "302", "200", "404", "404-200"];

/**
 * What the CMS `staging` branch builds to preview drafts of a markus-static site: the site build
 * command and the directory it writes. Without it, and without a `reader` to borrow them from,
 * the staging branch builds the newsroom only.
 */
export type StagingPreviewConfig = {
  buildCommand: string;
  baseDirectory: string;
};

export type CmsConfig = {
  appName?: string;
  domainName?: string;
  domainPrefix?: string;
  /** Public https origin of a site whose host is served by its own edge (no Amplify domain association). */
  siteOrigin?: string;
  staging?: boolean;
  stagingPreview?: StagingPreviewConfig;
  cognitoDomainPrefix: string;
  applyCognitoDomainPrefix?: boolean;
  buildComputeType?: "STANDARD" | "STANDARD_8GB";
  environment: Record<string, string>;
  stagingDomainName?: string;
  stagingDomainPrefix?: string;
  redirects?: CmsRedirect[];
  prospectusAccountsApiStageArn?: string;
  /**
   * The site is a public-reader site that polls Prospectus for retired reader subjects. The template then generates a
   * shared secret that the scheduled snapshot run presents to the CMS route `/api/reader/retired` (requires
   * `prospectusAccountsApiStageArn`; docs/reader-steering.md).
   */
  readerRetirementPoll?: boolean;
  deployStackInBuild?: boolean;
};

export type AmplifyAppShellSiteConfig = {
  siteId: string;
  repository: string;
  repositoryAccessTokenSecretArn?: string;
  brand: string;
  frontend: "pretext" | "markus-static";
  hostedZoneId?: string;
  stackName?: string;
  aws?: SiteAwsConfig;
  cms?: CmsConfig;
  /** Required for cloud CMS sites; independent of newsletter feature enablement. */
  email?: CloudEmailConfig;
  reader?: {
    appName?: string;
    domainName?: string;
    domainPrefixes?: string[];
    branchName?: string;
    buildCommand: string;
    baseDirectory: string;
    environment?: Record<string, string>;
    redirects?: ReaderRedirect[];
    customHeaders?: ReaderCustomHeaderRule[];
    preBuildCommands?: string[];
    skipContentExport?: boolean;
  };
  papyrusVersion: string;
  storagePreviewPrefix?: string;
  /**
   * The scheduled cloud knowledge run for this publication. The app-shell stack ignores it; it is validated by
   * infra/scheduled-jobs/lib/knowledge-run-config.ts, which owns the schema.
   */
  knowledgeRun?: unknown;
  /**
   * Merge-to-main deploy from GitHub Actions through OIDC. When true (the default) the stack creates the
   * `<siteId>-github-deploy` role and turns off Amplify's own auto-build on the production branches, so the
   * public repository's workflow is the only trigger. Set false for a site whose repository is private:
   * private repositories get no Actions minutes, so Amplify's own repository-connected auto-build stays on.
   */
  autoDeploy: boolean;
  github?: {
    owner: string;
    repo: string;
    branches: string[];
    ciCanDeployInfra: boolean;
    /**
     * GitHub's numeric ids of the owner and the repository. Repositories with the immutable OIDC subject
     * (`repo:<owner>@<ownerId>/<repo>@<repoId>:ref:...`, see `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`)
     * present that form instead of `repo:<owner>/<repo>:ref:...`; with both ids set, roles trust both forms.
     */
    ownerId?: number;
    repoId?: number;
  };
};

/**
 * Where the site's AWS resources live. `bin/app-shell.ts` deploys the stack into exactly this account and
 * region (see `resolveDeployEnvironment`), and `papyrus site google-secrets` asserts `accountId` with STS
 * before it writes anything.
 */
export type SiteAwsConfig = {
  profile?: string;
  accountId?: string;
  region?: string;
};

export type CmsSiteConfig = AmplifyAppShellSiteConfig & { cms: CmsConfig };

export function hasCmsApp(config: AmplifyAppShellSiteConfig): config is CmsSiteConfig {
  return config.cms !== undefined;
}

export function resolveGithubRepository(config: Pick<AmplifyAppShellSiteConfig, "repository" | "github">): { owner: string; repo: string } {
  if (config.github) return { owner: config.github.owner, repo: config.github.repo };
  const [owner, repo] = config.repository.replace("https://github.com/", "").split("/");
  return { owner, repo };
}

/** The OIDC `sub` values a GitHub Actions run on `ref` of the site's repository can present. */
export function githubOidcSubjects(config: Pick<AmplifyAppShellSiteConfig, "repository" | "github">, ref: string): string[] {
  const { owner, repo } = resolveGithubRepository(config);
  const subjects = [`repo:${owner}/${repo}:ref:refs/heads/${ref}`];
  const { ownerId, repoId } = config.github ?? {};
  if (ownerId !== undefined && repoId !== undefined) {
    subjects.push(`repo:${owner}@${ownerId}/${repo}@${repoId}:ref:refs/heads/${ref}`);
  }
  return subjects;
}

export const DEFAULT_CI_BRANCHES = ["main", "staging"];

const SITE_ID_PATTERN = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;
const REPOSITORY_PATTERN = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const SECRETS_MANAGER_SECRET_ARN_PATTERN = /^arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+$/;
const HOSTED_ZONE_ID_PATTERN = /^Z[A-Z0-9]+$/;
const HOST_NAME_PATTERN = /^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/;
const SITE_ORIGIN_PATTERN = /^https:\/\/([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(:\d{1,5})?$/;
const DOMAIN_PREFIX_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;
const APP_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _.-]*$/;
const STACK_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9-]{0,127}$/;
const BRANCH_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9/_.-]*$/;
const PAPYRUS_VERSION_PATTERN = /^\d+\.\d+\.\d+(-[0-9A-Za-z-]+\.\d+)?$/;
const GITHUB_OWNER_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const GITHUB_REPO_PATTERN = /^[A-Za-z0-9_.-]+$/;
const COGNITO_DOMAIN_PREFIX_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const COGNITO_RESERVED_WORDS = ["aws", "amazon", "cognito"];
const PROSPECTUS_ACCOUNTS_API_STAGE_ARN_PATTERN = /^arn:aws:execute-api:[a-z0-9-]+:\d{12}:[a-z0-9]+\/api$/;
const TEMPLATE_MANAGED_ENVIRONMENT_KEYS = ["PAPYRUS_EMAIL_FROM_ADDRESS", "PAPYRUS_EMAIL_IDENTITY_ARN", "PAPYRUS_EMAIL_CONFIGURATION_SET", "PAPYRUS_EMAIL_EVENT_TOPIC_NAME", "PAPYRUS_COGNITO_DOMAIN_PREFIX", "PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX", "PAPYRUS_DISABLE_GOOGLE_OAUTH", "PAPYRUS_REVALIDATE_SECRET_PARAMETER", "PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT", "PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER", "PAPYRUS_PROSPECTUS_SITE_PRODUCT", "PAPYRUS_READER_POLL_SECRET_PARAMETER", "PAPYRUS_SITE_ORIGIN"];

/** Routes Prospectus admits for a registered Papyrus site (Prospectus accounts/papyrus-sites.ts). */
export const PROSPECTUS_PAPYRUS_SITE_ROUTES = [
  "GET/v1/identities/me",
  "POST/v1/identities/google/challenge",
  "POST/v1/identities/google/resolve",
  "GET/v1/accounts",
  "GET/v1/accounts/*",
  "POST/v1/accounts/*/authorize",
  "GET/v1/account-directory",
  "GET/v1/account-directory/*",
];

export function resolveProspectusAccountsEndpoint(prospectusAccountsApiStageArn: string): string {
  const [, , , region, , apiPath] = prospectusAccountsApiStageArn.split(":");
  const [apiId, stageName] = apiPath.split("/");
  return `https://${apiId}.execute-api.${region}.amazonaws.com/${stageName}/`;
}
function originOfRedirectUrl(value: string): string {
  try {
    return new URL(value).origin;
  } catch {
    return value;
  }
}

export function resolveProspectusSessionSealingParameterName(config: Pick<AmplifyAppShellSiteConfig, "siteId">): string {
  return `/papyrus/${config.siteId}/prospectus-session-sealing`;
}

export function resolveReaderPollSecretParameterName(config: Pick<AmplifyAppShellSiteConfig, "siteId">): string {
  return `/papyrus/${config.siteId}/reader-poll-secret`;
}

export function resolveRevalidateSecretParameterName(config: Pick<AmplifyAppShellSiteConfig, "siteId">): string {
  return `/papyrus/${config.siteId}/revalidate-secret`;
}

const LOCAL_DEVELOPMENT_ORIGIN = "http://localhost:3001/";

function fail(field: string, problem: string): never {
  throw new Error(`site.json: ${field} ${problem}`);
}

function requireObject(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(field, "must be an object");
  }
  return value as Record<string, unknown>;
}

function requireString(value: unknown, field: string, pattern?: RegExp, patternHint?: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    fail(field, "must be a non-empty string");
  }
  if (pattern && !pattern.test(value as string)) {
    fail(field, `is invalid${patternHint ? ` (${patternHint})` : ""}: ${JSON.stringify(value)}`);
  }
  return value as string;
}

function optionalString(value: unknown, field: string, pattern?: RegExp, patternHint?: string): string | undefined {
  return value === undefined ? undefined : requireString(value, field, pattern, patternHint);
}

function requireStringRecord(value: unknown, field: string): Record<string, string> {
  const record = requireObject(value, field);
  const result: Record<string, string> = {};
  for (const [key, entry] of Object.entries(record)) {
    if (typeof entry !== "string") fail(`${field}.${key}`, "must be a string");
    result[key] = entry as string;
  }
  return result;
}

function rejectUnknownKeys(record: Record<string, unknown>, allowed: string[], field: string): void {
  for (const key of Object.keys(record)) {
    if (!allowed.includes(key)) fail(`${field}.${key}`, `is not a known field (known: ${allowed.join(", ")})`);
  }
}

function parseRedirects(value: unknown): CmsRedirect[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0) fail("cms.redirects", "must be a non-empty array");
  return (value as unknown[]).map((entry, index) => {
    const field = `cms.redirects[${index}]`;
    const record = requireObject(entry, field);
    rejectUnknownKeys(record, ["source", "status"], field);
    const source = requireString(record.source, `${field}.source`, HOST_NAME_PATTERN, "host name without scheme or path");
    const status = record.status ?? 301;
    if (status !== 301 && status !== 302) fail(`${field}.status`, `must be 301 or 302, got ${JSON.stringify(status)}`);
    return { source, status };
  });
}

function parseReaderDomainPrefixes(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0) fail("reader.domainPrefixes", "must be a non-empty array");
  const prefixes = (value as unknown[]).map((entry, index) => {
    const field = `reader.domainPrefixes[${index}]`;
    if (entry === "") return "";
    return requireString(entry, field, DOMAIN_PREFIX_PATTERN, 'single DNS label, or "" for the apex');
  });
  if (new Set(prefixes).size !== prefixes.length) fail("reader.domainPrefixes", "must not repeat a prefix");
  return prefixes;
}

function parseReaderRedirects(value: unknown): ReaderRedirect[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0) fail("reader.redirects", "must be a non-empty array");
  return (value as unknown[]).map((entry, index) => {
    const field = `reader.redirects[${index}]`;
    const record = requireObject(entry, field);
    rejectUnknownKeys(record, ["source", "target", "status"], field);
    const status = record.status ?? "301";
    if (typeof status !== "string" || !READER_REDIRECT_STATUSES.includes(status as ReaderRedirectStatus)) {
      fail(`${field}.status`, `must be one of ${READER_REDIRECT_STATUSES.join(", ")}, got ${JSON.stringify(status)}`);
    }
    return {
      source: requireString(record.source, `${field}.source`),
      target: requireString(record.target, `${field}.target`),
      status: status as ReaderRedirectStatus,
    };
  });
}

function parseReaderCustomHeaders(value: unknown): ReaderCustomHeaderRule[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0) fail("reader.customHeaders", "must be a non-empty array");
  return (value as unknown[]).map((entry, index) => {
    const field = `reader.customHeaders[${index}]`;
    const record = requireObject(entry, field);
    rejectUnknownKeys(record, ["pattern", "headers"], field);
    const headers = requireStringRecord(record.headers, `${field}.headers`);
    if (Object.keys(headers).length === 0) fail(`${field}.headers`, "must not be empty");
    return { pattern: requireString(record.pattern, `${field}.pattern`), headers };
  });
}

function parseReaderPreBuildCommands(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0) fail("reader.preBuildCommands", "must be a non-empty array of commands");
  return (value as unknown[]).map((command, index) => requireString(command, `reader.preBuildCommands[${index}]`));
}

export function resolveRedirectSubDomainPrefix(rootDomain: string, source: string): string {
  return source === rootDomain ? "" : source.slice(0, -rootDomain.length - 1);
}

export function isStagingEnabled(config: Pick<CmsSiteConfig, "cms">): boolean {
  return config.cms.staging !== false;
}

export function resolveCmsHostName(config: Pick<CmsSiteConfig, "cms">): string | undefined {
  if (!config.cms.domainName) return undefined;
  return config.cms.domainPrefix ? `${config.cms.domainPrefix}.${config.cms.domainName}` : config.cms.domainName;
}

export function resolveSiteOrigin(config: Pick<CmsSiteConfig, "cms">): string | undefined {
  return config.cms.siteOrigin;
}

export function resolveStagingDomainName(config: Pick<CmsSiteConfig, "cms">): string | undefined {
  if (!isStagingEnabled(config)) return undefined;
  if (config.cms.domainPrefix) {
    return config.cms.stagingDomainPrefix ? `${config.cms.stagingDomainPrefix}.${config.cms.domainName}` : undefined;
  }
  if (config.cms.stagingDomainName) return config.cms.stagingDomainName;
  if (!config.cms.domainName) return undefined;
  const [, ...rest] = config.cms.domainName.split(".");
  return ["staging", ...rest].join(".");
}

export function resolveStackName(config: Pick<AmplifyAppShellSiteConfig, "siteId" | "stackName">): string {
  return config.stackName ?? `amplify-app-shell-${config.siteId}`;
}

export function resolveStoragePreviewPrefix(config: Pick<AmplifyAppShellSiteConfig, "storagePreviewPrefix">): string {
  return config.storagePreviewPrefix ?? "preview/";
}

function parseStagingPreview(value: unknown): StagingPreviewConfig | undefined {
  if (value === undefined) return undefined;
  const record = requireObject(value, "cms.stagingPreview");
  rejectUnknownKeys(record, ["buildCommand", "baseDirectory"], "cms.stagingPreview");
  return {
    buildCommand: requireString(record.buildCommand, "cms.stagingPreview.buildCommand"),
    baseDirectory: requireString(record.baseDirectory, "cms.stagingPreview.baseDirectory"),
  };
}

function parseCms(value: unknown): CmsConfig {
  const cmsRecord = requireObject(value, "cms");
  rejectUnknownKeys(cmsRecord, ["appName", "domainName", "staging", "cognitoDomainPrefix", "applyCognitoDomainPrefix", "buildComputeType", "environment", "stagingDomainName", "domainPrefix", "siteOrigin", "stagingDomainPrefix", "redirects", "stagingPreview", "prospectusAccountsApiStageArn", "readerRetirementPoll", "deployStackInBuild"], "cms");
  const buildComputeType = cmsRecord.buildComputeType;
  if (buildComputeType !== undefined && buildComputeType !== "STANDARD" && buildComputeType !== "STANDARD_8GB") {
    fail("cms.buildComputeType", `must be "STANDARD" or "STANDARD_8GB", got ${JSON.stringify(buildComputeType)}`);
  }
  if (cmsRecord.staging !== undefined && typeof cmsRecord.staging !== "boolean") {
    fail("cms.staging", `must be a boolean, got ${JSON.stringify(cmsRecord.staging)}`);
  }
  if (cmsRecord.applyCognitoDomainPrefix !== undefined && typeof cmsRecord.applyCognitoDomainPrefix !== "boolean") {
    fail("cms.applyCognitoDomainPrefix", `must be a boolean, got ${JSON.stringify(cmsRecord.applyCognitoDomainPrefix)}`);
  }
  if (cmsRecord.readerRetirementPoll !== undefined && typeof cmsRecord.readerRetirementPoll !== "boolean") {
    fail("cms.readerRetirementPoll", `must be a boolean, got ${JSON.stringify(cmsRecord.readerRetirementPoll)}`);
  }
  if (cmsRecord.readerRetirementPoll === true && cmsRecord.prospectusAccountsApiStageArn === undefined) {
    fail("cms.readerRetirementPoll", "requires cms.prospectusAccountsApiStageArn: the poll calls Prospectus as the site");
  }
  if (cmsRecord.deployStackInBuild !== undefined && typeof cmsRecord.deployStackInBuild !== "boolean") {
    fail("cms.deployStackInBuild", `must be a boolean, got ${JSON.stringify(cmsRecord.deployStackInBuild)}`);
  }
  const cms: CmsConfig = {
    appName: optionalString(cmsRecord.appName, "cms.appName", APP_NAME_PATTERN),
    domainName: optionalString(cmsRecord.domainName, "cms.domainName", HOST_NAME_PATTERN, "host name"),
    domainPrefix: optionalString(cmsRecord.domainPrefix, "cms.domainPrefix", DOMAIN_PREFIX_PATTERN, "single DNS label"),
    siteOrigin: optionalString(cmsRecord.siteOrigin, "cms.siteOrigin", SITE_ORIGIN_PATTERN, "https origin with no path, query or trailing slash, such as https://shipped.anth.us"),
    staging: cmsRecord.staging as boolean | undefined,
    cognitoDomainPrefix: requireString(
      cmsRecord.cognitoDomainPrefix,
      "cms.cognitoDomainPrefix",
      COGNITO_DOMAIN_PREFIX_PATTERN,
      "lowercase letters, digits and hyphens; globally unique per region",
    ),
    applyCognitoDomainPrefix: cmsRecord.applyCognitoDomainPrefix as boolean | undefined,
    buildComputeType: buildComputeType as "STANDARD" | "STANDARD_8GB" | undefined,
    environment: requireStringRecord(cmsRecord.environment, "cms.environment"),
    stagingDomainName: optionalString(cmsRecord.stagingDomainName, "cms.stagingDomainName", HOST_NAME_PATTERN, "host name"),
    stagingDomainPrefix: optionalString(cmsRecord.stagingDomainPrefix, "cms.stagingDomainPrefix", DOMAIN_PREFIX_PATTERN, "single DNS label"),
    redirects: parseRedirects(cmsRecord.redirects),
    deployStackInBuild: cmsRecord.deployStackInBuild as boolean | undefined,
    readerRetirementPoll: cmsRecord.readerRetirementPoll as boolean | undefined,
    stagingPreview: parseStagingPreview(cmsRecord.stagingPreview),
    prospectusAccountsApiStageArn: optionalString(
      cmsRecord.prospectusAccountsApiStageArn,
      "cms.prospectusAccountsApiStageArn",
      PROSPECTUS_ACCOUNTS_API_STAGE_ARN_PATTERN,
      "arn:aws:execute-api:<region>:<account>:<api id>/api",
    ),
  };

  const reservedWord = COGNITO_RESERVED_WORDS.find((word) => cms.cognitoDomainPrefix.includes(word));
  if (reservedWord) {
    fail("cms.cognitoDomainPrefix", `must not contain "${reservedWord}" (Cognito reserves it): ${JSON.stringify(cms.cognitoDomainPrefix)}`);
  }
  for (const key of TEMPLATE_MANAGED_ENVIRONMENT_KEYS) {
    if (key in cms.environment) {
      fail(`cms.environment.${key}`, "is managed by the template: Google sign-in is always on, the Cognito domain comes from cms.cognitoDomainPrefix, the revalidation secret parameter is derived from siteId and the Prospectus endpoint comes from cms.prospectusAccountsApiStageArn and the public site origin comes from the site host");
    }
  }

  if (cms.siteOrigin && cms.domainName) {
    fail("cms.siteOrigin", "is for sites whose host is served by their own edge; remove it when cms.domainName is set");
  }
  if (cms.staging === false && cms.stagingDomainName) {
    fail("cms.stagingDomainName", "must not be set when cms.staging is false");
  }
  if (cms.stagingDomainName && !cms.domainName) {
    fail("cms.stagingDomainName", "requires cms.domainName");
  }
  if (cms.domainPrefix && !cms.domainName) {
    fail("cms.domainPrefix", "requires cms.domainName (the root domain)");
  }
  if (cms.stagingDomainPrefix && !cms.domainPrefix) {
    fail("cms.stagingDomainPrefix", "requires cms.domainPrefix");
  }
  if (cms.domainPrefix && cms.stagingDomainName) {
    fail("cms.stagingDomainName", "must not be set with cms.domainPrefix: use cms.stagingDomainPrefix");
  }
  if (cms.staging === false && cms.stagingDomainPrefix) {
    fail("cms.stagingDomainPrefix", "must not be set when cms.staging is false");
  }
  if (cms.domainPrefix && cms.staging !== false && !cms.stagingDomainPrefix) {
    fail("cms.stagingDomainPrefix", "is required when cms.domainPrefix is set and staging is enabled: the staging host is never derived under a shared root domain");
  }
  if (cms.domainPrefix && cms.stagingDomainPrefix === cms.domainPrefix) {
    fail("cms.stagingDomainPrefix", "must differ from cms.domainPrefix");
  }

  if (cms.redirects) {
    if (!cms.domainPrefix) fail("cms.redirects", "requires cms.domainPrefix (redirects target the primary host under a shared root domain)");
    cms.redirects.forEach((redirect, index) => {
      const field = `cms.redirects[${index}].source`;
      const root = cms.domainName as string;
      if (redirect.source !== root && !(redirect.source.endsWith(`.${root}`) && DOMAIN_PREFIX_PATTERN.test(redirect.source.slice(0, -root.length - 1)))) {
        fail(field, `must be the root domain ${root} or a single label under it: ${JSON.stringify(redirect.source)}`);
      }
      if (redirect.source === resolveCmsHostName({ cms })) fail(field, "must differ from the primary host");
      if (redirect.source === resolveStagingDomainName({ cms })) fail(field, "must differ from the staging host");
    });
    if (new Set(cms.redirects.map((redirect) => redirect.source)).size !== cms.redirects.length) {
      fail("cms.redirects", "must not repeat a source");
    }
  }

  return cms;
}

function validateOauthRedirectUrls(config: CmsSiteConfig): void {
  const redirectValue = config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS;
  if (redirectValue === undefined) fail("config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS", "is required");
  const redirectUrls = redirectValue.split(",").map((url) => url.trim());
  const stagingDomainName = resolveStagingDomainName(config);
  const listedOrigins = new Set(redirectUrls.map(originOfRedirectUrl));
  const requiredOrigins = [
    ...(resolveCmsHostName(config) ? [`https://${resolveCmsHostName(config)}`] : []),
    ...(stagingDomainName ? [`https://${stagingDomainName}`] : []),
    originOfRedirectUrl(LOCAL_DEVELOPMENT_ORIGIN),
  ];
  for (const origin of requiredOrigins) {
    if (!listedOrigins.has(origin)) {
      fail("config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS", `must include ${origin}/ (or just the origin: the backend also registers its newsroom path)`);
    }
  }
}

function parseAws(value: unknown): SiteAwsConfig | undefined {
  if (value === undefined) return undefined;
  const record = requireObject(value, "aws");
  rejectUnknownKeys(record, ["profile", "accountId", "region"], "aws");
  return {
    profile: optionalString(record.profile, "aws.profile", /^[A-Za-z0-9_.-]+$/, "AWS CLI profile name"),
    accountId: optionalString(record.accountId, "aws.accountId", /^\d{12}$/, "12-digit account id"),
    region: optionalString(record.region, "aws.region", /^[a-z]{2}(-[a-z]+)+-\d$/, "AWS region such as us-east-1"),
  };
}

export function parseSiteConfig(raw: unknown): AmplifyAppShellSiteConfig {
  const record = requireObject(raw, "site");
  rejectUnknownKeys(
    record,
    ["siteId", "repository", "repositoryAccessTokenSecretArn", "brand", "frontend", "hostedZoneId", "stackName", "aws", "cms", "email", "reader", "papyrusVersion", "storagePreviewPrefix", "knowledgeRun", "autoDeploy", "github"],
    "site",
  );

  const siteId = requireString(record.siteId, "siteId", SITE_ID_PATTERN, "kebab-case");
  const repository = requireString(record.repository, "repository", REPOSITORY_PATTERN, "https://github.com/<org>/<repo>");
  const repositoryAccessTokenSecretArn = record.repositoryAccessTokenSecretArn === undefined
    ? undefined
    : requireString(record.repositoryAccessTokenSecretArn, "repositoryAccessTokenSecretArn", SECRETS_MANAGER_SECRET_ARN_PATTERN, "Secrets Manager secret ARN");
  const brand = requireString(record.brand, "brand");
  const frontend = requireString(record.frontend, "frontend");
  if (frontend !== "pretext" && frontend !== "markus-static") {
    fail("frontend", `must be "pretext" or "markus-static", got ${JSON.stringify(frontend)}`);
  }
  const hostedZoneId = optionalString(record.hostedZoneId, "hostedZoneId", HOSTED_ZONE_ID_PATTERN, "Route 53 zone id");
  const stackName = optionalString(record.stackName, "stackName", STACK_NAME_PATTERN, "CloudFormation stack name");
  const aws = parseAws(record.aws);
  const papyrusVersion = requireString(record.papyrusVersion, "papyrusVersion", PAPYRUS_VERSION_PATTERN, "exact version such as 1.0.0 or 1.0.0-next.1");
  const storagePreviewPrefix = optionalString(record.storagePreviewPrefix, "storagePreviewPrefix", /^[A-Za-z0-9._-]+\/$/, "must end with /");

  const cms = record.cms === undefined && frontend === "markus-static" ? undefined : parseCms(record.cms);

  let reader: AmplifyAppShellSiteConfig["reader"];
  if (record.reader !== undefined) {
    if (frontend !== "markus-static") fail("reader", `is only allowed when frontend is "markus-static"`);
    const readerRecord = requireObject(record.reader, "reader");
    rejectUnknownKeys(readerRecord, ["appName", "domainName", "domainPrefixes", "branchName", "buildCommand", "baseDirectory", "environment", "redirects", "customHeaders", "preBuildCommands", "skipContentExport"], "reader");
    if (readerRecord.skipContentExport !== undefined && typeof readerRecord.skipContentExport !== "boolean") {
      fail("reader.skipContentExport", `must be a boolean, got ${JSON.stringify(readerRecord.skipContentExport)}`);
    }
    reader = {
      appName: optionalString(readerRecord.appName, "reader.appName", APP_NAME_PATTERN),
      domainName: optionalString(readerRecord.domainName, "reader.domainName", HOST_NAME_PATTERN, "host name"),
      branchName: optionalString(readerRecord.branchName, "reader.branchName", BRANCH_NAME_PATTERN),
      buildCommand: requireString(readerRecord.buildCommand, "reader.buildCommand"),
      baseDirectory: requireString(readerRecord.baseDirectory, "reader.baseDirectory"),
      environment: readerRecord.environment === undefined ? undefined : requireStringRecord(readerRecord.environment, "reader.environment"),
      domainPrefixes: parseReaderDomainPrefixes(readerRecord.domainPrefixes),
      redirects: parseReaderRedirects(readerRecord.redirects),
      customHeaders: parseReaderCustomHeaders(readerRecord.customHeaders),
      preBuildCommands: parseReaderPreBuildCommands(readerRecord.preBuildCommands),
      skipContentExport: readerRecord.skipContentExport as boolean | undefined,
    };
    if (reader.domainPrefixes && !reader.domainName) fail("reader.domainPrefixes", "requires reader.domainName");
  } else if (frontend === "markus-static" && cms === undefined) {
    fail("reader", `is required when frontend is "markus-static" and there is no cms section`);
  }
  if (cms?.stagingPreview !== undefined && frontend !== "markus-static") {
    fail("cms.stagingPreview", `is only allowed when frontend is "markus-static"`);
  }
  if (cms?.stagingPreview !== undefined && cms.staging === false) {
    fail("cms.stagingPreview", "must not be set when cms.staging is false");
  }

  const autoDeploy = record.autoDeploy ?? true;
  if (typeof autoDeploy !== "boolean") fail("autoDeploy", "must be a boolean");

  let github: AmplifyAppShellSiteConfig["github"];
  if (record.github !== undefined) {
    if (cms === undefined) fail("github", "requires cms (the CI role is scoped to the CMS app)");
    const githubRecord = requireObject(record.github, "github");
    rejectUnknownKeys(githubRecord, ["owner", "repo", "branches", "ciCanDeployInfra", "ownerId", "repoId"], "github");
    const owner = requireString(githubRecord.owner, "github.owner", GITHUB_OWNER_PATTERN, "plain GitHub login");
    const repo = requireString(githubRecord.repo, "github.repo", GITHUB_REPO_PATTERN);
    if (repository !== `https://github.com/${owner}/${repo}`) {
      fail("github", `owner/repo must match repository ${repository}`);
    }
    let branches = cms?.staging === false ? DEFAULT_CI_BRANCHES.filter((branch) => branch !== "staging") : DEFAULT_CI_BRANCHES;
    if (githubRecord.branches !== undefined) {
      if (!Array.isArray(githubRecord.branches) || githubRecord.branches.length === 0) {
        fail("github.branches", "must be a non-empty array of branch names");
      }
      branches = (githubRecord.branches as unknown[]).map((branch, index) => {
        if (typeof branch === "string" && /[*?]/.test(branch)) {
          fail(`github.branches[${index}]`, `must not contain wildcards: ${JSON.stringify(branch)}`);
        }
        return requireString(branch, `github.branches[${index}]`, BRANCH_NAME_PATTERN);
      });
    }
    const ciCanDeployInfra = githubRecord.ciCanDeployInfra ?? false;
    if (typeof ciCanDeployInfra !== "boolean") fail("github.ciCanDeployInfra", "must be a boolean");
    const optionalId = (value: unknown, name: string): number | undefined => {
      if (value === undefined) return undefined;
      if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) fail(name, "must be a positive integer (GitHub numeric id)");
      return value as number;
    };
    const ownerId = optionalId(githubRecord.ownerId, "github.ownerId");
    const repoId = optionalId(githubRecord.repoId, "github.repoId");
    if ((ownerId === undefined) !== (repoId === undefined)) fail("github", "ownerId and repoId must be set together");
    github = { owner, repo, branches, ciCanDeployInfra: ciCanDeployInfra as boolean, ...(ownerId !== undefined ? { ownerId, repoId } : {}) };
  }

  const hasDomain = cms?.domainName !== undefined || reader?.domainName !== undefined;
  if (hasDomain && hostedZoneId === undefined) {
    fail("hostedZoneId", "is required when cms.domainName or reader.domainName is set");
  }
  if (!hasDomain && hostedZoneId !== undefined) {
    fail("hostedZoneId", "is only allowed when cms.domainName or reader.domainName is set");
  }

  const config: AmplifyAppShellSiteConfig = {
    siteId,
    repository,
    repositoryAccessTokenSecretArn,
    brand,
    frontend,
    hostedZoneId,
    stackName,
    aws,
    cms,
    email: parseCloudEmail(record.email, cms !== undefined, siteId),
    reader,
    papyrusVersion,
    storagePreviewPrefix,
    autoDeploy: autoDeploy as boolean,
    github,
    ...(record.knowledgeRun !== undefined ? { knowledgeRun: record.knowledgeRun } : {}),
  };

  if (hasCmsApp(config)) validateOauthRedirectUrls(config);

  return config;
}

/**
 * The CDK environment for a site's app-shell stack, taken only from the site's own `aws` block. There is
 * deliberately no default account: a deploy that guesses an account can land in, or fail against, the wrong
 * one.
 */
export function resolveDeployEnvironment(config: Pick<AmplifyAppShellSiteConfig, "siteId" | "aws">): { account: string; region: string } {
  const account = config.aws?.accountId;
  const region = config.aws?.region;
  const missing = [account ? "" : "aws.accountId", region ? "" : "aws.region"].filter(Boolean);
  if (!account || !region) {
    throw new Error(
      `site "${config.siteId}" does not say where it deploys: add ${missing.join(" and ")} to its site.json, e.g. "aws": { "accountId": "<12-digit account>", "region": "us-east-1" }. No account is assumed.`,
    );
  }
  return { account, region };
}
