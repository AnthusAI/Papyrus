import { NextResponse, type NextRequest } from "next/server";
import { GetParameterCommand, SSMClient } from "@aws-sdk/client-ssm";
import { SiteOriginNotConfiguredError, publicSiteOrigin, siteOriginNotConfiguredResponse } from "./site-origin";
import { resolveProspectusSignInRuntime, type ProspectusSignInRuntime } from "./prospectus-session";
import { ProspectusAccountsError } from "./prospectus-site-identity";
import { secretsMatch } from "./revalidate-secret";

export const READER_POLL_SECRET_PARAMETER_ENV = "PAPYRUS_READER_POLL_SECRET_PARAMETER";
export const READER_POLL_SECRET_HEADER = "x-papyrus-reader-poll-secret";
export const READER_POLL_SECRET_CACHE_MILLISECONDS = 5 * 60 * 1000;
const CURSOR_PATTERN = /^[A-Za-z0-9._~=+/-]{1,512}$/;
const NO_STORE_HEADERS = { "cache-control": "no-store" };

export interface ReaderRetirementRouteOptions {
  environment?: Record<string, string | undefined>;
  readSecret?: (parameterName: string) => Promise<string | null>;
  resolveRuntime?: (siteOrigin: string) => Promise<Pick<ProspectusSignInRuntime, "accounts"> | null>;
  now?: number;
}

type CachedSecret = { parameterName: string; value: string; expiresAt: number };
let cachedSecret: CachedSecret | null = null;
let defaultSsmClient: SSMClient | null = null;

export function resetReaderPollSecretCache(): void {
  cachedSecret = null;
}

async function readSecretFromSsm(parameterName: string): Promise<string | null> {
  defaultSsmClient ??= new SSMClient({});
  const response = await defaultSsmClient.send(new GetParameterCommand({ Name: parameterName, WithDecryption: true }));
  return response.Parameter?.Value?.trim() || null;
}

async function loadReaderPollSecret(options: ReaderRetirementRouteOptions, environment: Record<string, string | undefined>): Promise<string | null> {
  const parameterName = environment[READER_POLL_SECRET_PARAMETER_ENV]?.trim();
  if (!parameterName) return null;
  const now = options.now ?? Date.now();
  if (cachedSecret && cachedSecret.parameterName === parameterName && cachedSecret.expiresAt > now) return cachedSecret.value;
  try {
    const value = (await (options.readSecret ?? readSecretFromSsm)(parameterName))?.trim();
    if (!value) return null;
    cachedSecret = { parameterName, value, expiresAt: now + READER_POLL_SECRET_CACHE_MILLISECONDS };
    return value;
  } catch (error) {
    console.error(`Reader poll secret could not be read (${error instanceof Error ? error.name : "error"}).`);
    return null;
  }
}

function failure(status: number, error: string, message: string): NextResponse {
  return NextResponse.json({ error, message }, { status, headers: NO_STORE_HEADERS });
}

/**
 * The scheduled snapshot run's way to Prospectus's retired-subject route. Prospectus admits one caller per site, this
 * app's compute role, so the run cannot call it directly: it calls this route with a shared secret from SSM, and the route
 * calls Prospectus as the compute role and passes the answer through. Anyone without the secret gets 401, and a site
 * without the secret parameter gets 503, so this is never open.
 */
export async function handleReaderRetiredSubjects(request: NextRequest, options: ReaderRetirementRouteOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const expected = await loadReaderPollSecret(options, environment);
  if (!expected) return failure(503, "reader_poll_unavailable", "The retirement poll is not configured for this site.");
  if (!secretsMatch(request.headers.get(READER_POLL_SECRET_HEADER), expected)) return failure(401, "unauthorized", "Missing or wrong poll secret.");

  const since = request.nextUrl.searchParams.get("since") ?? undefined;
  const unknownParameters = [...request.nextUrl.searchParams.keys()].filter((key) => key !== "since");
  if (unknownParameters.length > 0 || (since !== undefined && !CURSOR_PATTERN.test(since))) {
    return failure(400, "invalid_since", "Send only a since cursor.");
  }
  let siteOrigin: string;
  try {
    siteOrigin = publicSiteOrigin(request, environment);
  } catch (error) {
    if (error instanceof SiteOriginNotConfiguredError) return siteOriginNotConfiguredResponse(error);
    throw error;
  }
  const runtime = await (options.resolveRuntime ?? ((origin) => resolveProspectusSignInRuntime(origin, { environment })))(siteOrigin);
  if (!runtime) return failure(503, "prospectus_sign_in_unavailable", "Prospectus is not configured for this site.");
  try {
    const page = await runtime.accounts.retiredSiteSubjects(since);
    return NextResponse.json({ retired: page.retired, cursor: page.cursor, more: page.more }, { headers: NO_STORE_HEADERS });
  } catch (error) {
    if (error instanceof ProspectusAccountsError) return failure(error.status === 400 ? 400 : 502, error.code, error.message);
    console.error(`Prospectus retired subjects failed (${error instanceof Error ? error.name : "error"}).`);
    return failure(502, "prospectus_unavailable", "Prospectus could not be reached.");
  }
}
