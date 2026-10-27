import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import { SiteOriginNotConfiguredError, publicSiteOrigin, siteOriginNotConfiguredResponse } from "./site-origin";

/**
 * The public values `papyrus login <site>` needs, served at `/.well-known/papyrus-cli.json`.
 * Every value is public (Cognito pool/client ids, hosted-UI domain, API URL). Nothing here is a
 * secret, and the file only exists for a site whose web client registers the CLI callback.
 */
export const CLI_LOGIN_PATH = "/.well-known/papyrus-cli.json";

export interface CliLoginDocument {
  publication: string;
  issuer: string;
  client_id: string;
  oauth_domain: string;
  graphql_endpoint: string;
  callback_uri: string;
}

export interface AmplifyOutputsForCliLogin {
  auth?: {
    user_pool_id?: string;
    user_pool_client_id?: string;
    aws_region?: string;
    oauth?: { domain?: string; redirect_sign_in_uri?: string[] };
  };
  data?: { url?: string };
}

/**
 * The CLI signs in through the site's existing public web app client, which every app-shell site
 * registers with this callback (infra/amplify-app-shell/lib/site-config.ts). No separate client exists.
 */
export const CLI_CALLBACK_URI = "http://localhost:3001/";

export function cliLoginDocumentFromOutputs(outputs: AmplifyOutputsForCliLogin | null, siteOrigin: string): CliLoginDocument | null {
  const userPoolId = outputs?.auth?.user_pool_id;
  const clientId = outputs?.auth?.user_pool_client_id;
  const domain = outputs?.auth?.oauth?.domain;
  const endpoint = outputs?.data?.url;
  if (!userPoolId || !clientId || !domain || !endpoint || !endpoint.startsWith("https://")) return null;
  // Only when the client really registers the callback; otherwise the sign-in could never complete.
  if (!outputs?.auth?.oauth?.redirect_sign_in_uri?.includes(CLI_CALLBACK_URI)) return null;
  const region = outputs?.auth?.aws_region ?? userPoolId.split("_")[0];
  return {
    publication: siteOrigin,
    issuer: `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`,
    client_id: clientId,
    oauth_domain: `https://${domain}`,
    graphql_endpoint: endpoint,
    callback_uri: CLI_CALLBACK_URI,
  };
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
      { error: "cli_login_not_configured", message: "This site does not register the CLI sign-in callback." },
      { status: 404, headers: { "cache-control": "public, max-age=60" } },
    );
  }
  return NextResponse.json(document, { headers: { "cache-control": "public, max-age=300" } });
}
