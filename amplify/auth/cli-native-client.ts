import { CfnOutput, type Stack } from "aws-cdk-lib";
import { CfnUserPoolClient, CfnUserPoolIdentityProvider, type IUserPool } from "aws-cdk-lib/aws-cognito";

/**
 * The public native app client behind `papyrus login <site>` (docs/cli-login.md). It sits on the
 * site's existing user pool and admits only Google through authorization code + PKCE to one
 * registered loopback callback. No secret, no SRP/password flow, revocation on. Unlike the
 * Prospectus server client, it keeps a renewable refresh token (default 30 days).
 * A site opts in with `auth.cliLogin`; without it nothing is created and the site publishes no
 * `/.well-known/papyrus-cli.json`.
 */
export const DEFAULT_CLI_REFRESH_TOKEN_DAYS = 30;

export interface CliLoginConfig {
  /** Registered loopback callback, for example `http://localhost:5182/oauth/callback`. */
  callbackUri: string;
  refreshTokenValidityDays?: number;
}

export function assertLoopbackCallback(callbackUri: string): void {
  let url: URL;
  try {
    url = new URL(callbackUri);
  } catch {
    throw new Error("cliLogin.callbackUri must be a URL.");
  }
  const port = Number(url.port);
  if (url.protocol !== "http:" || (url.hostname !== "127.0.0.1" && url.hostname !== "localhost")
    || !Number.isInteger(port) || port < 1024 || port > 65535 || url.username || url.password || url.search || url.hash) {
    throw new Error("cliLogin.callbackUri must be http://127.0.0.1 or http://localhost with a fixed port from 1024 to 65535 and no credentials, query or fragment.");
  }
}

export function addCliNativeClient(authStack: Stack, userPool: IUserPool, config: CliLoginConfig): CfnUserPoolClient {
  assertLoopbackCallback(config.callbackUri);
  const refreshDays = config.refreshTokenValidityDays ?? DEFAULT_CLI_REFRESH_TOKEN_DAYS;
  const client = new CfnUserPoolClient(authStack, "PapyrusCliNativeClient", {
    userPoolId: userPool.userPoolId,
    clientName: "papyrus-cli-native",
    generateSecret: false,
    supportedIdentityProviders: ["Google"],
    allowedOAuthFlowsUserPoolClient: true,
    allowedOAuthFlows: ["code"],
    allowedOAuthScopes: ["openid", "email", "profile"],
    callbackUrLs: [config.callbackUri],
    explicitAuthFlows: ["ALLOW_REFRESH_TOKEN_AUTH"],
    enableTokenRevocation: true,
    preventUserExistenceErrors: "ENABLED",
    accessTokenValidity: 60,
    idTokenValidity: 60,
    refreshTokenValidity: refreshDays,
    tokenValidityUnits: { accessToken: "minutes", idToken: "minutes", refreshToken: "days" },
  });
  for (const provider of authStack.node.findAll()) {
    if (provider instanceof CfnUserPoolIdentityProvider && provider.providerName === "Google") client.addDependency(provider);
  }
  new CfnOutput(authStack, "PapyrusCliNativeClientId", {
    value: client.ref,
    description: "clientId served at /.well-known/papyrus-cli.json for `papyrus login <site>`",
  });
  return client;
}

export function cliLoginRefreshLifetimeSeconds(config: CliLoginConfig): number {
  return (config.refreshTokenValidityDays ?? DEFAULT_CLI_REFRESH_TOKEN_DAYS) * 24 * 3600;
}
