import { defineAuth, secret } from "@aws-amplify/backend";
import { manageUserRole } from "../functions/manage-user-role/resource";

// Default OAuth redirect URLs for the p.apyr.us app. Other publications
// override via the PAPYRUS_OAUTH_REDIRECT_URLS branch env var (comma-
// separated). See docs/google-oauth-setup.md.
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

const authRedirectUrls = resolveAuthRedirectUrls();

const disableGoogleOAuth = process.env.PAPYRUS_DISABLE_GOOGLE_OAUTH === "1";

// Stable Cognito hosted-UI domain prefix for Google OAuth redirect URIs.
// Set per publication via CDK app-shell branch env. See docs/google-oauth-setup.md.
const cognitoDomainPrefix = (process.env.PAPYRUS_COGNITO_DOMAIN_PREFIX ?? "").trim();

export const auth = defineAuth({
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
            ...(cognitoDomainPrefix ? { domainPrefix: cognitoDomainPrefix } : {}),
          },
        }),
  },
  groups: ["admin", "editor", "curator"],
  access: (allow) => [
    allow.resource(manageUserRole).to(["addUserToGroup", "removeUserFromGroup", "listUsers", "listGroupsForUser"]),
  ],
});
