import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import { SiteOriginNotConfiguredError, publicSiteOrigin, siteOriginNotConfiguredResponse } from "./site-origin";

/**
 * The public values `papyrus login <site>` needs, served at `/.well-known/papyrus-cli.json`.
 * Every value is public (Cognito pool/client ids, hosted-UI domain, API URL). Nothing here is a
 * secret, and the file only exists for a site whose backend declared a native CLI client.
 */
export const CLI_LOGIN_PATH = "/.well-known/papyrus-cli.json";

export interface CliLoginDocument {
  publication: string;
  issuer: string;
  client_id: string;
  oauth_domain: string;
  graphql_endpoint: string;
  callback_uri: string;
  refresh_lifetime_seconds?: number;
}

export interface AmplifyOutputsForCliLogin {
  auth?: { user_pool_id?: string; aws_region?: string; oauth?: { domain?: string } };
  data?: { url?: string };
  custom?: { cliLogin?: { clientId?: string; callbackUri?: string; refreshLifetimeSeconds?: number } | null };
}

/** The same rule the CLI applies: plain HTTP only to a loopback host on a fixed unprivileged port. */
export function isLoopbackCallback(value: string): boolean {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  const port = Number(url.port);
  return url.protocol === "http:" && (url.hostname === "127.0.0.1" || url.hostname === "localhost")
    && Number.isInteger(port) && port >= 1024 && port <= 65535
    && !url.username && !url.password && !url.search && !url.hash;
}

export function cliLoginDocumentFromOutputs(outputs: AmplifyOutputsForCliLogin | null, siteOrigin: string): CliLoginDocument | null {
  const userPoolId = outputs?.auth?.user_pool_id;
  const domain = outputs?.auth?.oauth?.domain;
  const endpoint = outputs?.data?.url;
  const cliLogin = outputs?.custom?.cliLogin;
  if (!userPoolId || !domain || !endpoint || !cliLogin?.clientId || !cliLogin.callbackUri) return null;
  if (!endpoint.startsWith("https://") || !isLoopbackCallback(cliLogin.callbackUri)) return null;
  const region = outputs?.auth?.aws_region ?? userPoolId.split("_")[0];
  const document: CliLoginDocument = {
    publication: siteOrigin,
    issuer: `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`,
    client_id: cliLogin.clientId,
    oauth_domain: `https://${domain}`,
    graphql_endpoint: endpoint,
    callback_uri: cliLogin.callbackUri,
  };
  if (typeof cliLogin.refreshLifetimeSeconds === "number" && cliLogin.refreshLifetimeSeconds > 0) {
    document.refresh_lifetime_seconds = cliLogin.refreshLifetimeSeconds;
  }
  return document;
}

export interface CliLoginDiscoveryOptions {
  readOutputs?: () => AmplifyOutputsForCliLogin | null;
  environment?: Record<string, string | undefined>;
}

export function handleCliLoginDiscovery(request: Pick<NextRequest, "nextUrl">, options: CliLoginDiscoveryOptions = {}): NextResponse {
  let origin: string;
  try {
    origin = publicSiteOrigin(request, options.environment ?? process.env);
  } catch (error) {
    if (error instanceof SiteOriginNotConfiguredError) return siteOriginNotConfiguredResponse(error);
    throw error;
  }
  const outputs = (options.readOutputs ?? (() => readAmplifyOutputsFile() as AmplifyOutputsForCliLogin | null))();
  const document = cliLoginDocumentFromOutputs(outputs, origin);
  if (!document) {
    return NextResponse.json(
      { error: "cli_login_not_configured", message: "This site has no native CLI sign-in client." },
      { status: 404, headers: { "cache-control": "public, max-age=60" } },
    );
  }
  return NextResponse.json(document, { headers: { "cache-control": "public, max-age=300" } });
}
