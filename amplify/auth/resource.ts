import { defineAuth, secret } from "@aws-amplify/backend";
import { manageUserRole } from "../functions/manage-user-role/resource";
import { Stack } from "aws-cdk-lib";
import { CfnUserPoolDomain, CfnUserPoolIdentityProvider } from "aws-cdk-lib/aws-cognito";
import type { PapyrusAuthConfig } from "../site-backend-config";
import { expandNewsroomRedirectUrls } from "./redirect-urls";

// Default OAuth redirect URLs for the p.apyr.us app. Other publications pass
// `auth.redirectUrls` to `defineSiteBackend` (or, for Papyrus's own backend,
// the PAPYRUS_OAUTH_REDIRECT_URLS branch env var, comma-separated).
// `defineSiteAuth` adds the newsroom and root variants of every origin listed.
// See docs/google-oauth-setup.md.
const DEFAULT_AUTH_REDIRECT_URLS = [
  "http://localhost:3001/",
  "http://localhost:3000/",
  "https://p.apyr.us/",
  "https://main.dbsyytcm9drqa.amplifyapp.com/",
  "https://codex-rehydration-api-split.dbsyytcm9drqa.amplifyapp.com/",
];

function resolveAuthRedirectUrls(): string[] {
  const raw = (process.env.PAPYRUS_OAUTH_REDIRECT_URLS ?? "").trim();
  if (!raw) return DEFAULT_AUTH_REDIRECT_URLS;
  return raw
    .split(",")
    .map((url) => url.trim())
    .filter((url) => url.length > 0);
}

function cliLoginFromEnv(): PapyrusAuthConfig["cliLogin"] {
  const callbackUri = (process.env.PAPYRUS_CLI_LOGIN_CALLBACK_URI ?? "").trim();
  return callbackUri ? { callbackUri } : undefined;
}

/** Auth config from the environment (what Papyrus's own backend uses today). */
export function authConfigFromEnv(): PapyrusAuthConfig {
  return {
    redirectUrls: resolveAuthRedirectUrls(),
    disableGoogleOAuth: process.env.PAPYRUS_DISABLE_GOOGLE_OAUTH === "1",
    cognitoDomainPrefix: (process.env.PAPYRUS_COGNITO_DOMAIN_PREFIX ?? "").trim(),
    applyCognitoDomainPrefix: process.env.PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX === "true",
    cliLogin: cliLoginFromEnv(),
  };
}

export function siteAuthRedirectUrls(config: PapyrusAuthConfig): string[] {
  return config.redirectUrls ?? DEFAULT_AUTH_REDIRECT_URLS;
}

/** Keep Cognito's federated email verification state in sync with Google's verified claim. */
export function applyGoogleEmailVerifiedMapping(authStack: Stack): void {
  const googleProviders = authStack.node
    .findAll()
    .filter((construct): construct is CfnUserPoolIdentityProvider =>
      construct instanceof CfnUserPoolIdentityProvider && construct.providerName === "Google");
  if (googleProviders.length !== 1) {
    throw new Error(`Expected exactly one Google identity provider to map email_verified, found ${googleProviders.length}`);
  }

  const [provider] = googleProviders;
  const mapping = provider.attributeMapping;
  if (mapping !== undefined && (typeof mapping !== "object" || Array.isArray(mapping))) {
    throw new Error("Expected Google identity provider attribute mappings to be a plain object");
  }
  provider.attributeMapping = { ...(mapping ?? {}), email_verified: "email_verified" };
}

export function defineSiteAuth(config: PapyrusAuthConfig) {
  const authRedirectUrls = expandNewsroomRedirectUrls(
    siteAuthRedirectUrls(config),
    config.newsroomBasePath,
  );
  const disableGoogleOAuth = config.disableGoogleOAuth === true;
  return defineAuth({
    loginWith: {
      email: true,
      ...(disableGoogleOAuth
        ? {}
        : {
            externalProviders: {
              google: {
                clientId: secret("GOOGLE_CLIENT_ID"),
                clientSecret: secret("GOOGLE_CLIENT_SECRET"),
                scopes: ["email", "profile", "openid"],
              },
              scopes: ["EMAIL", "PROFILE", "OPENID"],
              callbackUrls: authRedirectUrls,
              logoutUrls: authRedirectUrls,
            },
          }),
    },
    groups: ["admin", "editor", "curator"],
    access: (allow) => [
      allow.resource(manageUserRole).to(["addUserToGroup", "removeUserFromGroup", "listUsers", "listGroupsForUser"]),
    ],
  });
}

// Amplify Gen2's auth factory overwrites `externalProviders.domainPrefix` with a
// hash of the backend id, so the prefix cannot be passed through `defineAuth`.
// This sets the user pool domain on the synthesized resource instead. Cognito
// cannot rename a pool domain in place: CloudFormation replaces the domain,
// which changes the hosted-UI URL and the Google redirect URI. Callers must
// only use it when the site opted in (see docs/google-oauth-setup.md).
export function applyCognitoDomainPrefix(authStack: Stack, cognitoDomainPrefix: string): void {
  const domainResources = authStack.node
    .findAll()
    .filter((construct): construct is CfnUserPoolDomain => construct instanceof CfnUserPoolDomain);
  if (domainResources.length !== 1) {
    throw new Error(
      `Expected exactly one Cognito user pool domain in the auth stack to apply cognitoDomainPrefix, found ${domainResources.length}`,
    );
  }
  domainResources[0].domain = cognitoDomainPrefix;
}
