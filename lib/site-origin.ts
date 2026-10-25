import { NextResponse } from "next/server";
import { SiteOriginNotConfiguredError } from "./site-origin-value";

export { SITE_ORIGIN_ENV, SiteOriginNotConfiguredError, publicSiteOrigin, publicSiteUrl } from "./site-origin-value";

export function siteOriginNotConfiguredResponse(error: SiteOriginNotConfiguredError): NextResponse {
  return NextResponse.json({ error: error.code, message: error.message }, { status: error.status, headers: { "cache-control": "no-store" } });
}
