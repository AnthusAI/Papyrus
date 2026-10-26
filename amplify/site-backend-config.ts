import type { PluginRequest } from "./plugins/types";

/**
 * Per-site backend configuration: the argument of `defineSiteBackend(site)`.
 * Config is passed in; the environment is only a fallback so Papyrus's own
 * `amplify/backend.ts` keeps its current behaviour.
 */
export type PapyrusAuthConfig = {
  /** OAuth callback/logout URLs for Google sign-in (ignored when Google is disabled). */
  redirectUrls?: string[];
  disableGoogleOAuth?: boolean;
  /**
   * Public newsroom path prefix for sign-in return URLs. Default `/newsroom`;
   * `""` on a CMS-only host where the newsroom is the root. Filled from the
   * active brand's `newsroomBasePath` by `defineSiteBackend` when unset.
   */
  newsroomBasePath?: string;
  /** Desired Cognito hosted-UI domain prefix. Only applied when `applyCognitoDomainPrefix` is true. */
  cognitoDomainPrefix?: string;
  /**
   * Opt in to the prefix. Off by default because changing a live pool's
   * domain replaces it and changes the Google redirect URI.
   */
  applyCognitoDomainPrefix?: boolean;
};

export type S3ProjectionDistributionConfig = {
  create: boolean;
  aliases?: string[];
  certificateArn?: string;
  acm?: { hostedZoneId: string; hostedZoneName: string };
};

export type PapyrusPublicationCacheConfig = {
  /** Shared-cache lifetime (seconds) of projected HTML. Default 300 with targeted invalidation, 60 with `invalidation: "off"`. */
  htmlSMaxAgeSeconds?: number;
  /** `targeted` (default): purge exactly the written paths after each projection. `off`: rely on the short lifetime alone. */
  invalidation?: "targeted" | "off";
};

export const MAXIMUM_HTML_S_MAXAGE_SECONDS = 86400;

export type PapyrusMonitoringConfig = {
  /** Existing shared Monitoring partition that stores this site's private email receipts. */
  emailMonitorId?: string;
};

const MONITOR_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;

export function validateMonitoringConfig(monitoring: unknown): string[] {
  if (monitoring === undefined) return [];
  if (typeof monitoring !== "object" || monitoring === null || Array.isArray(monitoring)) {
    return ["monitoring must be an object"];
  }
  const config = monitoring as { emailMonitorId?: unknown };
  if (config.emailMonitorId !== undefined
    && (typeof config.emailMonitorId !== "string" || !MONITOR_ID_PATTERN.test(config.emailMonitorId))) {
    return ["monitoring.emailMonitorId must be a lowercase monitor id (1-63 letters, digits, or hyphens)"];
  }
  return [];
}

export function assertValidMonitoringConfig(monitoring: unknown): void {
  const problems = validateMonitoringConfig(monitoring);
  if (problems.length > 0) throw new Error(`Invalid backend.monitoring: ${problems.join("; ")}`);
}

export type PapyrusPublicationConfig = {
  kind: "s3-projection";
  /** Site repo path (relative, `.py`) of the SiteProjector bundled into content-actions as `site_projector`. */
  projector?: string;
  /** Site repo directory (relative) bundled into content-actions as `site_static/`. */
  staticDir?: string;
  /** Existing CloudFront distribution that reads the site bucket through OAC. */
  edgeDistributionArn?: string;
  /** Edge cache lifetime of projected HTML and whether each projection purges the edge. */
  cache?: PapyrusPublicationCacheConfig;
  /** Create the distribution (and optionally its certificate) in the site backend. Default: not created. */
  distribution?: S3ProjectionDistributionConfig;
  /** Default true: the site bucket is retained when the stack is deleted. `false` destroys it and its objects. */
  retainBucketOnDelete?: boolean;
  /**
   * Re-project every published page after each backend deploy, so a theme or code change reaches the
   * site without a manual `papyrus ops content project --all`. Default: true for the publication a
   * Markus site gets when it sets none, false when `publication` is written out in the site config.
   */
  reprojectOnDeploy?: boolean;
};

const CLOUDFRONT_DISTRIBUTION_ARN = /^arn:aws[a-z-]*:cloudfront::\d{12}:distribution\/[A-Z0-9]+$/;

function isRelativePathWithoutParentSegments(value: string): boolean {
  if (value === "" || value.startsWith("/") || value.includes("\\")) return false;
  return !value.split("/").includes("..");
}

export function validatePublicationConfig(publication: unknown): string[] {
  const problems: string[] = [];
  if (typeof publication !== "object" || publication === null) {
    return ["publication must be an object"];
  }
  const config = publication as Partial<PapyrusPublicationConfig> & { kind?: unknown };
  if (config.kind !== "s3-projection") {
    problems.push(`publication.kind must be "s3-projection" (got ${JSON.stringify(config.kind)})`);
  }
  if (config.projector !== undefined) {
    if (typeof config.projector !== "string" || !isRelativePathWithoutParentSegments(config.projector) || !config.projector.endsWith(".py")) {
      problems.push("publication.projector must be a relative .py path without '..'");
    }
  }
  if (config.staticDir !== undefined) {
    if (typeof config.staticDir !== "string" || !isRelativePathWithoutParentSegments(config.staticDir)) {
      problems.push("publication.staticDir must be a relative path without '..'");
    }
  }
  if (config.edgeDistributionArn !== undefined && !CLOUDFRONT_DISTRIBUTION_ARN.test(config.edgeDistributionArn)) {
    problems.push("publication.edgeDistributionArn must be a CloudFront distribution ARN (arn:aws:cloudfront::<account>:distribution/<id>)");
  }
  if (config.reprojectOnDeploy !== undefined && typeof config.reprojectOnDeploy !== "boolean") {
    problems.push("publication.reprojectOnDeploy must be a boolean");
  }
  const cache = config.cache;
  if (cache !== undefined) {
    const lifetime = cache.htmlSMaxAgeSeconds;
    if (lifetime !== undefined && (!Number.isInteger(lifetime) || lifetime < 0 || lifetime > MAXIMUM_HTML_S_MAXAGE_SECONDS)) {
      problems.push(`publication.cache.htmlSMaxAgeSeconds must be an integer from 0 to ${MAXIMUM_HTML_S_MAXAGE_SECONDS}`);
    }
    if (cache.invalidation !== undefined && cache.invalidation !== "targeted" && cache.invalidation !== "off") {
      problems.push('publication.cache.invalidation must be "targeted" or "off"');
    }
  }
  const distribution = config.distribution;
  if (distribution !== undefined) {
    if (config.edgeDistributionArn !== undefined && distribution.create === true) {
      problems.push("publication.edgeDistributionArn and publication.distribution.create are mutually exclusive");
    }
    const aliases = distribution.aliases ?? [];
    if (aliases.length > 0 && distribution.create !== true) {
      problems.push("publication.distribution.aliases require distribution.create to be true");
    }
    if (aliases.length > 0 && !distribution.certificateArn && !distribution.acm) {
      problems.push("publication.distribution.aliases require certificateArn or acm");
    }
    if (distribution.acm !== undefined && (!distribution.acm.hostedZoneId || !distribution.acm.hostedZoneName)) {
      problems.push("publication.distribution.acm requires hostedZoneId and hostedZoneName");
    }
  }
  return problems;
}

export function assertValidPublicationConfig(publication: unknown): void {
  const problems = validatePublicationConfig(publication);
  if (problems.length > 0) throw new Error(`Invalid backend.publication: ${problems.join("; ")}`);
}

export type PapyrusSiteBackendConfig = {
  /** Brand id; namespaces account-global resources (S3 Vectors index name). */
  brandId?: string;
  /**
   * Amplify app id whose `main` branch is this site's production pipeline.
   * Owns the account-global resources (SES rule set, backup vault, legacy
   * S3 Vectors index name). Unset for sandbox/scratch/new sites.
   */
  productionAppId?: string;
  auth?: PapyrusAuthConfig;
  /** Shared Monitoring partition used by private email intake for this publication. */
  monitoring?: PapyrusMonitoringConfig;
  /**
   * Maximum number of data model nested stacks CloudFormation creates at once.
   * Stacks are chained in waves of this size so a new AWS account is not hit
   * with every AppSync CreateResolver call in parallel (429). Only adds
   * DependsOn ordering; no resource changes. Default 12; 0 turns it off.
   */
  resolverWaveSize?: number;
  /**
   * Optional model groups to leave out of the data API (see `OPTIONAL_MODEL_GROUPS`; today `editions`).
   * CloudFormation allows 2,500 resources per stack operation, nested stacks included, and a fresh create of the full
   * model set exceeds it. Deploy a new site once with a group excluded, then remove the exclusion and deploy again:
   * the second deploy is an ordinary update that adds the models.
   */
  excludeModelGroups?: string[];
  /** Static reader app (Markus-static sites) that a publish rebuilds through IAM `amplify:StartJob`. */
  reader?: { amplifyAppId: string; branchName?: string };
  /** Lets the newsroom start the `staging` branch build of this CMS app. */
  stagingBuild?: { enabled: boolean };
  /** Base URL of a Pretext reader whose `/api/revalidate` a publish calls (authenticated by the SSM secret named in branch variable `PAPYRUS_REVALIDATE_SECRET_PARAMETER`). */
  revalidateBaseUrl?: string;
  /**
   * CloudFront distribution ids (same account) in front of that reader. After a publish refreshes the reader's
   * cache, content-actions invalidates the revalidated paths on each of them. Needs `revalidateBaseUrl`.
   */
  revalidateDistributionIds?: string[];
  /**
   * SES receipt options for a site that is not the legacy p.apyr.us backend.
   * By default the site gets its own brand-named rule set that is never
   * activated by CloudFormation (SES allows one active rule set per account/region).
   */
  inboundEmailSes?: {
    /** Add this site's rule to a rule set another stack owns instead of creating one. */
    existingReceiptRuleSetName?: string;
    /** Let this stack verify the SES domain identity and write its TXT record. Default false: verify once by hand. */
    manageDomainIdentity?: boolean;
  };
  /**
   * Static projection of published pages into an S3 site bucket. Unset: a Markus site without a
   * `reader` gets `{ kind: "s3-projection" }`; any other site gets nothing. `false` opts a Markus
   * site out. See `resolveSitePublication`.
   */
  publication?: PapyrusPublicationConfig | false;
  /**
   * Deploy-time plugins (docs/plugins.md): `["signup"]`, or `[{ name: "signup", forms: ["news"] }]`.
   * Unset: no plugin, and the synthesized backend is exactly what it was before plugins existed.
   */
  plugins?: PluginRequest[];
  /**
   * The public form receiving endpoint every site gets (docs/public-forms.md). It accepts posts only from the site's
   * own public hosts (distribution aliases, reader domain, revalidate URL, sign-in redirect URLs) plus these.
   */
  publicForms?: {
    /** Extra https origins (or http://localhost) allowed to post, for example `https://www.example.org`. */
    allowedOrigins?: string[];
    /** Extra honeypot field names besides `website`. */
    honeypotFields?: string[];
  };
  features?: {
    consoleResponder?: boolean;
    inboundEmail?: boolean;
    slack?: boolean;
    storageBackups?: boolean;
  };
};
