/**
 * Per-site backend configuration: the argument of `defineSiteBackend(site)`.
 * Config is passed in; the environment is only a fallback so Papyrus's own
 * `amplify/backend.ts` keeps its current behaviour.
 */
export type PapyrusAuthConfig = {
  /** OAuth callback/logout URLs for Google sign-in (ignored when Google is disabled). */
  redirectUrls?: string[];
  disableGoogleOAuth?: boolean;
  /** Stable Cognito hosted-UI domain prefix. */
  cognitoDomainPrefix?: string;
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
  /** Base URL of a Pretext reader whose `/api/revalidate` a publish calls (secret `PAPYRUS_REVALIDATE_SECRET`). */
  revalidateBaseUrl?: string;
  features?: {
    consoleResponder?: boolean;
    inboundEmail?: boolean;
    slack?: boolean;
    storageBackups?: boolean;
  };
};
