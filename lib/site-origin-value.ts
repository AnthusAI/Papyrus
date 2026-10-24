import type { NextRequest } from "next/server";
import { getSiteEnv } from "./site-env";

type EnvironmentVariables = Record<string, string | undefined>;

export const SITE_ORIGIN_ENV = "PAPYRUS_SITE_ORIGIN";

export class SiteOriginNotConfiguredError extends Error {
  readonly status = 503;
  readonly code = "site_origin_not_configured";
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

/** The site's public origin from trusted configuration, never Host or forwarded headers. */
export function publicSiteOrigin(request: Pick<NextRequest, "nextUrl">, environment: EnvironmentVariables = process.env): string {
  const configured = (environment[SITE_ORIGIN_ENV] ?? "").trim();
  if (configured) return configuredOrigin(configured);
  const { hostname, origin } = request.nextUrl;
  const developing = siteEnvOrNull(environment) === "development" && environment.NODE_ENV !== "production";
  if (isLoopbackHostname(hostname) && developing) return origin;
  throw new SiteOriginNotConfiguredError(`${SITE_ORIGIN_ENV} is not set; this site cannot tell its public origin.`);
}

/** An absolute URL on the site's trusted public origin. */
export function publicSiteUrl(path: string, request: Pick<NextRequest, "nextUrl">, environment: EnvironmentVariables = process.env): URL {
  return new URL(path, publicSiteOrigin(request, environment));
}
