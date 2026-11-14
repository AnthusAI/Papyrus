import type { Stack } from "aws-cdk-lib";
import { CfnUserPoolClient, CfnUserPoolDomain, CfnUserPoolIdentityProvider } from "aws-cdk-lib/aws-cognito";
import type { AlexaWiringStep } from "../contracts";
import { HOSTED_UI_ORIGIN_ENVIRONMENT_VARIABLE } from "../review/newsroom";

/** The Lambda environment contract the access token verifier reads. */
export const ALEXA_USER_POOL_ID_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_USER_POOL_ID";
export const ALEXA_CLIENT_ID_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_CLIENT_ID";

export const ALEXA_CLIENT_TOKEN_VALIDITY_MINUTES = 60;
export const ALEXA_CLIENT_REFRESH_VALIDITY_DAYS = 365;

/** Amazon's account-linking redirect URLs, one per Alexa region, for the vendor ID of the developer account that owns the skill. */
export function alexaRedirectUrls(amazonVendorId: string): string[] {
  return ["pitangui.amazon.com", "layla.amazon.com", "alexa.amazon.co.jp"].map((host) => `https://${host}/api/skill/link/${amazonVendorId}`);
}

/**
 * The dedicated Alexa app client on the site's own user pool, only when the site turned account linking on. It admits only the
 * built-in Google provider through the authorization code flow, with a generated secret (Alexa authenticates to the token endpoint
 * with it) and refresh tokens (Alexa refreshes on its own). No SRP, password or custom auth. The secret is never copied anywhere:
 * the skill deploy reads it with DescribeUserPoolClient when it syncs the skill's account linking.
 */
export const alexaCognitoClientStep: AlexaWiringStep = (backend, config, _context, lambda) => {
  if (!config.accountLinking) return;
  if (config.amazonVendorId === undefined) throw new Error("alexa accountLinking needs amazonVendorId");
  const authStack: Stack = backend.auth.stack;
  const userPool = backend.auth.resources.userPool;

  const client = new CfnUserPoolClient(authStack, "AlexaAccountLinkingClient", {
    userPoolId: userPool.userPoolId,
    clientName: "papyrus-alexa-account-linking",
    generateSecret: true,
    supportedIdentityProviders: ["Google"],
    allowedOAuthFlowsUserPoolClient: true,
    allowedOAuthFlows: ["code"],
    allowedOAuthScopes: ["openid", "email", "profile"],
    callbackUrLs: alexaRedirectUrls(config.amazonVendorId),
    explicitAuthFlows: ["ALLOW_REFRESH_TOKEN_AUTH"],
    enableTokenRevocation: true,
    preventUserExistenceErrors: "ENABLED",
    accessTokenValidity: ALEXA_CLIENT_TOKEN_VALIDITY_MINUTES,
    idTokenValidity: ALEXA_CLIENT_TOKEN_VALIDITY_MINUTES,
    refreshTokenValidity: ALEXA_CLIENT_REFRESH_VALIDITY_DAYS,
    tokenValidityUnits: { accessToken: "minutes", idToken: "minutes", refreshToken: "days" },
  });
  const googleProviders = authStack.node
    .findAll()
    .filter((construct): construct is CfnUserPoolIdentityProvider => construct instanceof CfnUserPoolIdentityProvider && construct.providerName === "Google");
  if (googleProviders.length === 0) throw new Error("alexa accountLinking signs in with Google, but the site has no Google identity provider.");
  for (const provider of googleProviders) client.addDependency(provider);

  const domains = authStack.node.findAll().filter((construct): construct is CfnUserPoolDomain => construct instanceof CfnUserPoolDomain);
  if (domains.length !== 1) throw new Error(`alexa accountLinking expects exactly one Cognito user pool domain, found ${domains.length}`);
  const hostedUiDomain = `${domains[0].domain}.auth.${authStack.region}.amazoncognito.com`;

  lambda.addEnvironment(ALEXA_USER_POOL_ID_ENVIRONMENT_VARIABLE, userPool.userPoolId);
  lambda.addEnvironment(ALEXA_CLIENT_ID_ENVIRONMENT_VARIABLE, client.ref);
  lambda.addEnvironment(HOSTED_UI_ORIGIN_ENVIRONMENT_VARIABLE, `https://${hostedUiDomain}`);
  // Amplify merges outputs deeply, so this sits beside custom.alexa.functionArn.
  backend.addOutput({ custom: { alexa: { accountLinking: { userPoolId: userPool.userPoolId, clientId: client.ref, hostedUiDomain } } } });
};
