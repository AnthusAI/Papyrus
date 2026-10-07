import { defineAuth, secret } from "@aws-amplify/backend";
import { manageUserRole } from "../functions/manage-user-role/resource";
import { Stack } from "aws-cdk-lib";
import { CfnUserPoolDomain } from "aws-cdk-lib/aws-cognito";
import type { PapyrusAuthConfig } from "../site-backend-config";

// Default OAuth redirect URLs for the p.apyr.us app. Other publications pass
// `auth.redirectUrls` to `defineSiteBackend` (or, for Papyrus's own backend,
// the PAPYRUS_OAUTH_REDIRECT_URLS branch env var, comma-separated).
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

/** Auth config from the environment (what Papyrus's own backend uses today). */
export function authConfigFromEnv(): PapyrusAuthConfig {
  return {
    redirectUrls: resolveAuthRedirectUrls(),
    disableGoogleOAuth: process.env.PAPYRUS_DISABLE_GOOGLE_OAUTH === "1",
    cognitoDomainPrefix: (process.env.PAPYRUS_COGNITO_DOMAIN_PREFIX ?? "").trim(),
    applyCognitoDomainPrefix: process.env.PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX === "true",
  };
}

export function defineSiteAuth(config: PapyrusAuthConfig) {
  const authRedirectUrls = config.redirectUrls ?? DEFAULT_AUTH_REDIRECT_URLS;
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
