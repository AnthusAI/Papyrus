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
  /** Static reader app (Markus-static sites) that a publish rebuilds through IAM `amplify:StartJob`. */
  reader?: { amplifyAppId: string; branchName?: string };
  /** Lets the newsroom start the `staging` branch build of this CMS app. */
  stagingBuild?: { enabled: boolean };
  /** Base URL of a Pretext reader whose `/api/revalidate` a publish calls (authenticated by the SSM secret named in branch variable `PAPYRUS_REVALIDATE_SECRET_PARAMETER`). */
  revalidateBaseUrl?: string;
  /**
   * SES receipt options for a site that is not the legacy p.apyr.us backend.
   * By default the site gets its own brand-named rule set that is never
   * activated by CloudFormation (SES allows one active rule set per region).
   */
  inboundEmailSes?: {
    /** Add this site's rule to a rule set another stack owns instead of creating one. */
    existingReceiptRuleSetName?: string;
    /** Let this stack verify the SES domain identity and write its TXT record. Default false: verify once by hand. */
    manageDomainIdentity?: boolean;
  };
  features?: {
    consoleResponder?: boolean;
    inboundEmail?: boolean;
    slack?: boolean;
    storageBackups?: boolean;
  };
};
