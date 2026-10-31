import { CfnOutput, type Stack } from "aws-cdk-lib";
import { CfnUserPoolClient, CfnUserPoolIdentityProvider, type IUserPool } from "aws-cdk-lib/aws-cognito";

/**
 * The Google-only app client a Papyrus site registers with Prospectus
 * (Prospectus docs/accounts/GOOGLE_IDENTITY.md, policy google-only-unlinked-v1).
 * It lives on the site's existing user pool next to the email + Google web
 * client, but admits only the built-in Google provider through code + PKCE from
 * the site server, with every native, SRP, custom and client-credentials path
 * left off. Sessions last one access token: the server keeps no refresh token.
 * `extraCallbackUrls` is how a site that moved the CLI onto this client (`cliOnFederationClient`) adds the CLI's fixed
 * loopback callback and `<console origin>/cli/callback` (the console origin when the console has its own host, else the site origin); without it the client is exactly what it was.
 */
export const PROSPECTUS_SIGN_IN_CALLBACK_PATH = "/api/auth/prospectus/callback";
export const PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES = 60;
/** A site that moves the CLI onto this client keeps CLI sessions for seven days; access and ID tokens stay at 60 minutes. */
export const CLI_FEDERATION_REFRESH_TOKEN_VALIDITY_DAYS = 7;
/** Same value as lib/cli-loopback-callback.ts (the site cannot be imported from the packaged backend); a test keeps them equal. */
export const CLI_LOOPBACK_CALLBACK = "http://127.0.0.1:38947/cli/callback";
const CLI_REMOTE_CALLBACK_PATH = "/cli/callback";

export function prospectusSignInCallbackUrls(redirectUrls: readonly string[]): string[] {
  const origins: string[] = [];
  for (const redirectUrl of redirectUrls) {
    try {
      const origin = new URL(redirectUrl).origin;
      if (origin !== "null" && !origins.includes(origin)) origins.push(origin);
    } catch {
      continue;
    }
  }
  return origins.map((origin) => `${origin}${PROSPECTUS_SIGN_IN_CALLBACK_PATH}`);
}

export function prospectusSignInLogoutUrls(redirectUrls: readonly string[], extraCallbackUrls: readonly string[] = []): string[] {
  const logoutUrls: string[] = [];
  for (const callbackUrl of [...prospectusSignInCallbackUrls(redirectUrls), ...extraCallbackUrls]) {
    const logoutUrl = `${new URL(callbackUrl).origin}/`;
    if (!logoutUrls.includes(logoutUrl)) logoutUrls.push(logoutUrl);
  }
  return logoutUrls;
}

/**
 * The callbacks the CLI needs on the federation client when `cliOnFederationClient` is on: the fixed loopback and the
 * console's own `/cli/callback`. Off returns nothing, so the client is unchanged.
 */
export function cliFederationClientCallbackUrls(enabled: boolean, environment: Record<string, string | undefined>): string[] {
  if (!enabled) return [];
  const originText = (environment.PAPYRUS_CONSOLE_ORIGIN ?? environment.PAPYRUS_SITE_ORIGIN ?? "").trim();
  let origin: URL;
  try {
    origin = new URL(originText);
  } catch {
    throw new Error("Moving the CLI onto the federation client needs PAPYRUS_SITE_ORIGIN (or PAPYRUS_CONSOLE_ORIGIN when the console has its own host), the console's public https origin.");
  }
  if (origin.protocol !== "https:" || origin.pathname !== "/" || origin.search !== "" || origin.username !== "") {
    throw new Error(`Moving the CLI onto the federation client needs the console origin (PAPYRUS_CONSOLE_ORIGIN, else PAPYRUS_SITE_ORIGIN) to be a plain https origin, got ${originText}.`);
  }
  return [CLI_LOOPBACK_CALLBACK, `${origin.origin}${CLI_REMOTE_CALLBACK_PATH}`];
}

export function addProspectusGoogleOnlyClient(
  authStack: Stack,
  userPool: IUserPool,
  redirectUrls: readonly string[],
  extraCallbackUrls: readonly string[] = [],
  refreshTokenValidityDays?: number,
): CfnUserPoolClient {
  const callbackUrls = [...prospectusSignInCallbackUrls(redirectUrls)];
  if (callbackUrls.length === 0) throw new Error("The Prospectus Google-only client needs at least one site origin.");
  for (const extraCallbackUrl of extraCallbackUrls) if (!callbackUrls.includes(extraCallbackUrl)) callbackUrls.push(extraCallbackUrl);
  const googleOnlyClient = new CfnUserPoolClient(authStack, "ProspectusGoogleOnlyClient", {
    userPoolId: userPool.userPoolId,
    clientName: "prospectus-google-only",
    generateSecret: false,
    supportedIdentityProviders: ["Google"],
    allowedOAuthFlowsUserPoolClient: true,
    allowedOAuthFlows: ["code"],
    allowedOAuthScopes: ["openid", "email", "profile"],
    callbackUrLs: callbackUrls,
    logoutUrLs: prospectusSignInLogoutUrls(redirectUrls, extraCallbackUrls),
    explicitAuthFlows: ["ALLOW_REFRESH_TOKEN_AUTH"],
    enableTokenRevocation: true,
    preventUserExistenceErrors: "ENABLED",
    accessTokenValidity: PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES,
    idTokenValidity: PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES,
    refreshTokenValidity: refreshTokenValidityDays ?? PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES,
    tokenValidityUnits: { accessToken: "minutes", idToken: "minutes", refreshToken: refreshTokenValidityDays === undefined ? "minutes" : "days" },
  });
  const googleIdentityProviders = authStack.node
    .findAll()
    .filter((construct): construct is CfnUserPoolIdentityProvider => construct instanceof CfnUserPoolIdentityProvider && construct.providerName === "Google");
  for (const googleIdentityProvider of googleIdentityProviders) googleOnlyClient.addDependency(googleIdentityProvider);

  new CfnOutput(authStack, "ProspectusGoogleOnlyClientId", {
    value: googleOnlyClient.ref,
    description: "clientId for this site's Prospectus registration (accounts/papyrus-sites.json)",
  });
  new CfnOutput(authStack, "ProspectusGoogleOnlyIssuer", {
    value: `https://cognito-idp.${authStack.region}.amazonaws.com/${userPool.userPoolId}`,
    description: "issuer for this site's Prospectus registration (accounts/papyrus-sites.json)",
  });
  return googleOnlyClient;
}
