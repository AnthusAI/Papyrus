import { CfnOutput, type Stack } from "aws-cdk-lib";
import { CfnUserPoolClient, CfnUserPoolIdentityProvider, type IUserPool } from "aws-cdk-lib/aws-cognito";

/**
 * The Google-only app client a Papyrus site registers with Prospectus
 * (Prospectus docs/accounts/GOOGLE_IDENTITY.md, policy google-only-unlinked-v1).
 * It lives on the site's existing user pool next to the email + Google web
 * client, but admits only the built-in Google provider through code + PKCE from
 * the site server, with every native, SRP, custom and client-credentials path
 * left off. Sessions last one access token: the server keeps no refresh token.
 */
export const PROSPECTUS_SIGN_IN_CALLBACK_PATH = "/api/auth/prospectus/callback";
export const PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES = 60;

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

export function prospectusSignInLogoutUrls(redirectUrls: readonly string[]): string[] {
  return prospectusSignInCallbackUrls(redirectUrls).map((callbackUrl) => `${new URL(callbackUrl).origin}/`);
}

export function addProspectusGoogleOnlyClient(
  authStack: Stack,
  userPool: IUserPool,
  redirectUrls: readonly string[],
): CfnUserPoolClient {
  const callbackUrls = prospectusSignInCallbackUrls(redirectUrls);
  if (callbackUrls.length === 0) throw new Error("The Prospectus Google-only client needs at least one site origin.");
  const googleOnlyClient = new CfnUserPoolClient(authStack, "ProspectusGoogleOnlyClient", {
    userPoolId: userPool.userPoolId,
    clientName: "prospectus-google-only",
    generateSecret: false,
    supportedIdentityProviders: ["Google"],
    allowedOAuthFlowsUserPoolClient: true,
    allowedOAuthFlows: ["code"],
    allowedOAuthScopes: ["openid", "email", "profile"],
    callbackUrLs: callbackUrls,
    logoutUrLs: prospectusSignInLogoutUrls(redirectUrls),
    explicitAuthFlows: ["ALLOW_REFRESH_TOKEN_AUTH"],
    enableTokenRevocation: true,
    preventUserExistenceErrors: "ENABLED",
    accessTokenValidity: PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES,
    idTokenValidity: PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES,
    refreshTokenValidity: PROSPECTUS_SIGN_IN_TOKEN_VALIDITY_MINUTES,
    tokenValidityUnits: { accessToken: "minutes", idToken: "minutes", refreshToken: "minutes" },
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
