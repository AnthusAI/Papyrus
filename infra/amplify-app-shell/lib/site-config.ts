export type AmplifyAppShellSiteConfig = {
  siteId: string;
  repository: string;
  brand: string;
  frontend: "pretext" | "markus-static";
  hostedZoneId?: string;
  stackName?: string;
  cms: {
    appName?: string;
    domainName?: string;
    staging?: boolean;
    cognitoDomainPrefix: string;
    buildComputeType?: "STANDARD" | "STANDARD_8GB";
    environment: Record<string, string>;
    stagingDomainName?: string;
  };
  reader?: {
    appName?: string;
    domainName?: string;
    branchName?: string;
    buildCommand: string;
    baseDirectory: string;
    environment?: Record<string, string>;
  };
  papyrusVersion: string;
  storagePreviewPrefix?: string;
  github?: {
    owner: string;
    repo: string;
    branches: string[];
    ciCanDeployInfra: boolean;
  };
};

export const DEFAULT_CI_BRANCHES = ["main", "staging"];

const SITE_ID_PATTERN = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;
const REPOSITORY_PATTERN = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const HOSTED_ZONE_ID_PATTERN = /^Z[A-Z0-9]+$/;
const HOST_NAME_PATTERN = /^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/;
const APP_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _.-]*$/;
const STACK_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9-]{0,127}$/;
const BRANCH_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9/_.-]*$/;
const PAPYRUS_VERSION_PATTERN = /^\d+\.\d+\.\d+(-[0-9A-Za-z-]+\.\d+)?$/;
const GITHUB_OWNER_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const GITHUB_REPO_PATTERN = /^[A-Za-z0-9_.-]+$/;
const COGNITO_DOMAIN_PREFIX_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const COGNITO_RESERVED_WORDS = ["aws", "amazon", "cognito"];
const TEMPLATE_MANAGED_ENVIRONMENT_KEYS = ["PAPYRUS_COGNITO_DOMAIN_PREFIX", "PAPYRUS_DISABLE_GOOGLE_OAUTH"];
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

export function isStagingEnabled(config: Pick<AmplifyAppShellSiteConfig, "cms">): boolean {
  return config.cms.staging !== false;
}

export function resolveStagingDomainName(config: Pick<AmplifyAppShellSiteConfig, "cms">): string | undefined {
  if (!isStagingEnabled(config)) return undefined;
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

export function parseSiteConfig(raw: unknown): AmplifyAppShellSiteConfig {
  const record = requireObject(raw, "site");
  rejectUnknownKeys(
    record,
    ["siteId", "repository", "brand", "frontend", "hostedZoneId", "stackName", "cms", "reader", "papyrusVersion", "storagePreviewPrefix", "github"],
    "site",
  );

  const siteId = requireString(record.siteId, "siteId", SITE_ID_PATTERN, "kebab-case");
  const repository = requireString(record.repository, "repository", REPOSITORY_PATTERN, "https://github.com/<org>/<repo>");
  const brand = requireString(record.brand, "brand");
  const frontend = requireString(record.frontend, "frontend");
  if (frontend !== "pretext" && frontend !== "markus-static") {
    fail("frontend", `must be "pretext" or "markus-static", got ${JSON.stringify(frontend)}`);
  }
  const hostedZoneId = optionalString(record.hostedZoneId, "hostedZoneId", HOSTED_ZONE_ID_PATTERN, "Route 53 zone id");
  const stackName = optionalString(record.stackName, "stackName", STACK_NAME_PATTERN, "CloudFormation stack name");
  const papyrusVersion = requireString(record.papyrusVersion, "papyrusVersion", PAPYRUS_VERSION_PATTERN, "exact version such as 1.0.0 or 1.0.0-next.1");
  const storagePreviewPrefix = optionalString(record.storagePreviewPrefix, "storagePreviewPrefix", /^[A-Za-z0-9._-]+\/$/, "must end with /");

  const cmsRecord = requireObject(record.cms, "cms");
  rejectUnknownKeys(cmsRecord, ["appName", "domainName", "staging", "cognitoDomainPrefix", "buildComputeType", "environment", "stagingDomainName"], "cms");
  const buildComputeType = cmsRecord.buildComputeType;
  if (buildComputeType !== undefined && buildComputeType !== "STANDARD" && buildComputeType !== "STANDARD_8GB") {
    fail("cms.buildComputeType", `must be "STANDARD" or "STANDARD_8GB", got ${JSON.stringify(buildComputeType)}`);
  }
  if (cmsRecord.staging !== undefined && typeof cmsRecord.staging !== "boolean") {
    fail("cms.staging", `must be a boolean, got ${JSON.stringify(cmsRecord.staging)}`);
  }
  const cms: AmplifyAppShellSiteConfig["cms"] = {
    appName: optionalString(cmsRecord.appName, "cms.appName", APP_NAME_PATTERN),
    domainName: optionalString(cmsRecord.domainName, "cms.domainName", HOST_NAME_PATTERN, "host name"),
    staging: cmsRecord.staging as boolean | undefined,
    cognitoDomainPrefix: requireString(
      cmsRecord.cognitoDomainPrefix,
      "cms.cognitoDomainPrefix",
      COGNITO_DOMAIN_PREFIX_PATTERN,
      "lowercase letters, digits and hyphens; globally unique per region",
    ),
    buildComputeType: buildComputeType as "STANDARD" | "STANDARD_8GB" | undefined,
    environment: requireStringRecord(cmsRecord.environment, "cms.environment"),
    stagingDomainName: optionalString(cmsRecord.stagingDomainName, "cms.stagingDomainName", HOST_NAME_PATTERN, "host name"),
  };

  const reservedWord = COGNITO_RESERVED_WORDS.find((word) => cms.cognitoDomainPrefix.includes(word));
  if (reservedWord) {
    fail("cms.cognitoDomainPrefix", `must not contain "${reservedWord}" (Cognito reserves it): ${JSON.stringify(cms.cognitoDomainPrefix)}`);
  }
  for (const key of TEMPLATE_MANAGED_ENVIRONMENT_KEYS) {
    if (key in cms.environment) {
      fail(`cms.environment.${key}`, "is managed by the template: Google sign-in is always on and the Cognito domain comes from cms.cognitoDomainPrefix");
    }
  }

  if (cms.staging === false && cms.stagingDomainName) {
    fail("cms.stagingDomainName", "must not be set when cms.staging is false");
  }
  if (cms.stagingDomainName && !cms.domainName) {
    fail("cms.stagingDomainName", "requires cms.domainName");
  }

  let reader: AmplifyAppShellSiteConfig["reader"];
  if (record.reader !== undefined) {
    if (frontend !== "markus-static") fail("reader", `is only allowed when frontend is "markus-static"`);
    const readerRecord = requireObject(record.reader, "reader");
    rejectUnknownKeys(readerRecord, ["appName", "domainName", "branchName", "buildCommand", "baseDirectory", "environment"], "reader");
    reader = {
      appName: optionalString(readerRecord.appName, "reader.appName", APP_NAME_PATTERN),
      domainName: optionalString(readerRecord.domainName, "reader.domainName", HOST_NAME_PATTERN, "host name"),
      branchName: optionalString(readerRecord.branchName, "reader.branchName", BRANCH_NAME_PATTERN),
      buildCommand: requireString(readerRecord.buildCommand, "reader.buildCommand"),
      baseDirectory: requireString(readerRecord.baseDirectory, "reader.baseDirectory"),
      environment: readerRecord.environment === undefined ? undefined : requireStringRecord(readerRecord.environment, "reader.environment"),
    };
  } else if (frontend === "markus-static") {
    fail("reader", `is required when frontend is "markus-static"`);
  }

  let github: AmplifyAppShellSiteConfig["github"];
  if (record.github !== undefined) {
    const githubRecord = requireObject(record.github, "github");
    rejectUnknownKeys(githubRecord, ["owner", "repo", "branches", "ciCanDeployInfra"], "github");
    const owner = requireString(githubRecord.owner, "github.owner", GITHUB_OWNER_PATTERN, "plain GitHub login");
    const repo = requireString(githubRecord.repo, "github.repo", GITHUB_REPO_PATTERN);
    if (repository !== `https://github.com/${owner}/${repo}`) {
      fail("github", `owner/repo must match repository ${repository}`);
    }
    let branches = cms.staging === false ? DEFAULT_CI_BRANCHES.filter((branch) => branch !== "staging") : DEFAULT_CI_BRANCHES;
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
    github = { owner, repo, branches, ciCanDeployInfra: ciCanDeployInfra as boolean };
  }

  const hasDomain = cms.domainName !== undefined || reader?.domainName !== undefined;
  if (hasDomain && hostedZoneId === undefined) {
    fail("hostedZoneId", "is required when cms.domainName or reader.domainName is set");
  }
  if (!hasDomain && hostedZoneId !== undefined) {
    fail("hostedZoneId", "is only allowed when cms.domainName or reader.domainName is set");
  }

  const config: AmplifyAppShellSiteConfig = {
    siteId,
    repository,
    brand,
    frontend,
    hostedZoneId,
    stackName,
    cms,
    reader,
    papyrusVersion,
    storagePreviewPrefix,
    github,
  };

  const redirectValue = cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS;
  if (redirectValue === undefined) fail("cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS", "is required");
  const redirectUrls = redirectValue.split(",").map((url) => url.trim());
  const stagingDomainName = resolveStagingDomainName(config);
  const requiredOrigins = [
    ...(cms.domainName ? [`https://${cms.domainName}/`] : []),
    ...(stagingDomainName ? [`https://${stagingDomainName}/`] : []),
    LOCAL_DEVELOPMENT_ORIGIN,
  ];
  for (const origin of requiredOrigins) {
    if (!redirectUrls.includes(origin)) {
      fail("cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS", `must include ${origin}`);
    }
  }

  return config;
}
