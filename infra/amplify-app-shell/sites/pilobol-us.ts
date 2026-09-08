/**
 * Per-site configuration for the Amplify app-shell CDK stack.
 *
 * A site = one Papyrus publication CMS deployed as its own Amplify WEB_COMPUTE
 * app. The static reader is a separate Amplify WEB app (documented in
 * `readerDeployment` on the brand) and is NOT provisioned here.
 *
 * Add a new site by exporting a new entry below and selecting it via
 * `-c site=<id>` or the `site` CDK context variable.
 */

export type AmplifyAppShellSiteConfig = {
  /** CDK context selector and stack id suffix. */
  siteId: string;
  /** Amplify app name (also the CloudFormation stack-friendly id). */
  appName: string;
  /** Human description shown in the Amplify console. */
  description: string;
  /** GitHub repo URL the CMS deploys from. */
  repository: string;
  /** Amplify platform. Papyrus CMS is always WEB_COMPUTE (Next.js SSR). */
  platform: "WEB_COMPUTE";
  /** Deploy branch. */
  branchName: string;
  /** Branch environment variables (PAPYRUS_SITE_BRAND etc.). */
  environment: Record<string, string>;
  /**
   * Secrets Manager secret name holding the GitHub access token used by
   * Amplify to clone the repo. CDK reads it via a dynamic reference so the
   * token never lands in the CloudFormation template. Populate the secret
   * before deploying. Replace the initial token with a dedicated fine-grained
   * PAT scoped to this repo.
   */
  githubTokenSecretName: string;
  /** Custom domain for the CMS (newsroom.<site>.us). Apex stays on the reader. */
  domainName: string;
  /** Route 53 hosted zone id for the domain. */
  hostedZoneId: string;
  /** Build compute type. */
  buildComputeType?: "STANDARD" | "STANDARD_8GB";
  /** Enable branch auto-build so pushes trigger deploys. */
  enableAutoBuild?: boolean;
};

export const SITES: Record<string, AmplifyAppShellSiteConfig> = {
  "pilobol-us": {
    siteId: "pilobol-us",
    appName: "pilobol-us-cms",
    description: "Pilobolus Papyrus newsroom/CMS (WEB_COMPUTE); reader stays on d1od6t7lzbwanr",
    repository: "https://github.com/AnthusAI/Papyrus",
    platform: "WEB_COMPUTE",
    branchName: "main",
    environment: {
      PAPYRUS_SITE_BRAND: "pilobol-us",
      NEXT_PUBLIC_PAPYRUS_SITE_BRAND: "pilobol-us",
      PAPYRUS_CONTENT_SOURCE: "graphql",
      PAPYRUS_EDITION_SLUG: "current",
      PAPYRUS_ENABLE_CONSOLE_RESPONDER: "false",
      PAPYRUS_ENABLE_SLACK: "false",
      PAPYRUS_ENABLE_INBOUND_EMAIL: "false",
      PAPYRUS_ENABLE_STORAGE_BACKUPS: "false",
      PAPYRUS_DISABLE_GOOGLE_OAUTH: "1",
      // Used only when Google OAuth is enabled (see docs/google-oauth-setup.md).
      // Listed now so the app is ready to enable Google login by setting
      // GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET and removing the disable flag.
      PAPYRUS_OAUTH_REDIRECT_URLS: "http://localhost:3001/,https://newsroom.pilobol.us/,https://main.d11eu9hbs2mipk.amplifyapp.com/",
    },
    githubTokenSecretName: "amplify/github-app-token",
    domainName: "newsroom.pilobol.us",
    hostedZoneId: "Z09961547QX1VHIXOBD7",
    buildComputeType: "STANDARD_8GB",
    enableAutoBuild: true,
  },
};

export function resolveSite(siteId: string | undefined): AmplifyAppShellSiteConfig {
  const id = (siteId ?? "").trim();
  const config = SITES[id];
  if (!config) {
    throw new Error(
      `Unknown site '${id}'. Known sites: ${Object.keys(SITES).join(", ")}. Pass -c site=<id>.`,
    );
  }
  return config;
}
