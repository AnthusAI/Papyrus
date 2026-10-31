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
  /** Present only for a site that switched on `papyrus login --remote` (docs/cli-login.md). */
  broker_endpoint?: string;
  remote_callback_uri?: string;
}

export interface AmplifyOutputsForCliLogin {
  auth?: {
    user_pool_id?: string;
    user_pool_client_id?: string;
    aws_region?: string;
    oauth?: { domain?: string; redirect_sign_in_uri?: string[] };
  };
  data?: { url?: string };
  custom?: { cliLogin?: { brokerEndpoint?: string; remoteCallbackUri?: string; pagesFunctionArn?: string } | null };
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
  const remote = remoteLoginFromOutputs(outputs, siteOrigin);
  return {
    publication: siteOrigin,
    issuer: `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`,
    client_id: clientId,
    oauth_domain: `https://${domain}`,
    graphql_endpoint: endpoint,
    callback_uri: CLI_CALLBACK_URI,
    ...remote,
  };
}

/**
 * The broker, only when everything remote login needs is in place: the backend published a broker on an https URL, the
 * remote callback is this site's own `/cli/callback`, and the web client registers it. Otherwise the file says nothing
 * about remote login, so the CLI reports that the site has not switched it on.
 */
function remoteLoginFromOutputs(outputs: AmplifyOutputsForCliLogin | null, siteOrigin: string): Pick<CliLoginDocument, "broker_endpoint" | "remote_callback_uri"> | null {
  const published = outputs?.custom?.cliLogin;
  const broker = published?.brokerEndpoint;
  const callback = published?.remoteCallbackUri;
  if (!broker || !callback || !broker.startsWith("https://") || callback !== `${siteOrigin}/cli/callback`) return null;
  if (!outputs?.auth?.oauth?.redirect_sign_in_uri?.includes(callback)) return null;
  return { broker_endpoint: broker, remote_callback_uri: callback };
}

export interface CliLoginDiscoveryOptions {
  readOutputs?: () => AmplifyOutputsForCliLogin | null;
  environment?: Record<string, string | undefined>;
}

const CONSOLE_ORIGIN_ENV = "PAPYRUS_CONSOLE_ORIGIN";

/**
 * The origin the file names as the site: the console origin when the console has its own host (PAPYRUS_CONSOLE_ORIGIN), else the
 * site origin. The CLI requires `publication` to equal the origin it was given, and `papyrus login --remote` lives on the console
 * host, so that host is the address to sign in at. The public host serves the same file.
 */
function loginOrigin(siteOrigin: string, environment: Record<string, string | undefined>): string {
  const consoleOrigin = (environment[CONSOLE_ORIGIN_ENV] ?? "").trim();
  return consoleOrigin === "" ? siteOrigin : consoleOrigin;
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
  const document = cliLoginDocumentFromOutputs(outputs, loginOrigin(origin, options.environment ?? process.env));
  if (!document) {
    return NextResponse.json(
      { error: "cli_login_not_configured", message: "This site does not register the CLI sign-in callback." },
      { status: 404, headers: { "cache-control": "public, max-age=60" } },
    );
  }
  return NextResponse.json(document, { headers: { "cache-control": "public, max-age=300" } });
}
