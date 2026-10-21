import { NextResponse, type NextRequest } from "next/server";
import { getSiteEnv } from "./site-env";

type EnvironmentVariables = Record<string, string | undefined>;

export const SITE_ORIGIN_ENV = "PAPYRUS_SITE_ORIGIN";

/**
 * The site's public origin cannot be read from the request on Amplify SSR (WEB_COMPUTE):
 * there `request.nextUrl.origin` is the compute adapter's internal https://localhost:3000.
 * It also must never be derived from Host or X-Forwarded-* headers, which a client can set.
 * The one trusted source is PAPYRUS_SITE_ORIGIN, set by the app shell from the site's host.
 */
export class SiteOriginNotConfiguredError extends Error {
  readonly status = 503;
  readonly code = "site_origin_not_configured";
}

export function siteOriginNotConfiguredResponse(error: SiteOriginNotConfiguredError): NextResponse {
  return NextResponse.json({ error: error.code, message: error.message }, { status: error.status, headers: { "cache-control": "no-store" } });
}

function isLoopbackHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function configuredOrigin(value: string): string {
  const invalid = () => new SiteOriginNotConfiguredError(`${SITE_ORIGIN_ENV} must be an https origin such as https://example.com with no path.`);
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw invalid();
  }
  if (parsed.protocol !== "https:" || parsed.origin !== value) throw invalid();
  return parsed.origin;
}

function siteEnvOrNull(environment: EnvironmentVariables): string | null {
  try {
    return getSiteEnv(environment);
  } catch {
    return null;
  }
}

/**
 * The site's public origin, from trusted configuration.
 * - PAPYRUS_SITE_ORIGIN set: it must be an https origin with no path; it is used as is.
 * - Unset: `request.nextUrl.origin` only when it is loopback, SITE_ENV resolves to development
 *   and NODE_ENV is not production (a local `next dev` server). Anything else, production and staging included, throws
 *   SiteOriginNotConfiguredError so routes answer 503 instead of redirecting to localhost.
 */
export function publicSiteOrigin(request: Pick<NextRequest, "nextUrl">, environment: EnvironmentVariables = process.env): string {
  const configured = (environment[SITE_ORIGIN_ENV] ?? "").trim();
  if (configured) return configuredOrigin(configured);
  const { hostname, origin } = request.nextUrl;
  // SITE_ENV defaults to development when a runtime never received it, so NODE_ENV=production also closes the fallback.
  const developing = siteEnvOrNull(environment) === "development" && environment.NODE_ENV !== "production";
  if (isLoopbackHostname(hostname) && developing) return origin;
  throw new SiteOriginNotConfiguredError(`${SITE_ORIGIN_ENV} is not set; this site cannot tell its public origin.`);
}

/** An absolute URL on the site's public origin, for redirects. Fails closed like publicSiteOrigin. */
export function publicSiteUrl(path: string, request: Pick<NextRequest, "nextUrl">, environment: EnvironmentVariables = process.env): URL {
  return new URL(path, publicSiteOrigin(request, environment));
}
