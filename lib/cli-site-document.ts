import { NextResponse } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import { getPublicNewsroomBasePath } from "./newsroom-base-path";

/**
 * What the CLI may know about a site besides how to sign in, served at `/.well-known/papyrus-site.json`: the site's tenant id
 * (only when it has one), the Papyrus version it runs, and the media bucket and Cognito identity pool a signed-in editor
 * uploads pictures with (`stories save-version --images`), read from the site's own amplify_outputs.json. It is a second file
 * on purpose. `papyrus-cli.json` is read strictly by every installed CLI and refuses unknown fields, so nothing may be added
 * there. A CLI that has never heard of this file simply never asks for it. All values are public and none is a credential: the
 * tenant scopes requests and authorizes nothing; the bucket is private and reached only through the identity pool's role,
 * which a signed-in token must be traded for.
 */
export const SITE_DOCUMENT_PATH = "/.well-known/papyrus-site.json";

export interface SiteDocument {
  /** The site's PAPYRUS_TENANT_ID build variable; absent for a site with no tenant. */
  tenant_id?: string;
  /** The @anthusai/papyrus version the site was built with; absent when it cannot be told (a checkout of the engine). */
  papyrus_version?: string;
  /** The Amplify Storage bucket that holds the site's media; absent when the site's outputs name none. */
  media_bucket?: string;
  /** The Cognito identity pool a signed-in token is traded with for S3 credentials; absent when the outputs name none. */
  identity_pool_id?: string;
  /** Where the newsroom console is (its origin plus the path it is served at, no trailing slash), so a link to one item can be built without guessing. Absent when the site's origin is not configured. */
  console_url?: string;
}

/** The parts of the site's amplify_outputs.json this file reads. */
export interface SiteOutputs {
  storage?: { bucket_name?: string };
  auth?: { identity_pool_id?: string };
}

export interface SiteDocumentEnvironment {
  PAPYRUS_TENANT_ID?: string;
  PAPYRUS_ENGINE_VERSION?: string;
  /** The public site's origin; the console is at this origin unless PAPYRUS_CONSOLE_ORIGIN says it has its own host. */
  PAPYRUS_SITE_ORIGIN?: string;
  PAPYRUS_CONSOLE_ORIGIN?: string;
  /** The path the console is served at on its host: "/newsroom", or "" on a console-only host (the brand's newsroomBasePath). */
  newsroomBasePath?: string;
}

const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;
const BUCKET_PATTERN = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;
const IDENTITY_POOL_PATTERN = /^[a-z]{2}(?:-[a-z]+)+-\d:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const HTTPS_ORIGIN_PATTERN = /^https:\/\/[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?$/;
const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]{1,40})?$/;

export function siteDocument(environment: SiteDocumentEnvironment, outputs: SiteOutputs | null = null): SiteDocument {
  const tenant = (environment.PAPYRUS_TENANT_ID ?? "").trim();
  const version = (environment.PAPYRUS_ENGINE_VERSION ?? "").trim();
  const bucket = (outputs?.storage?.bucket_name ?? "").trim();
  const pool = (outputs?.auth?.identity_pool_id ?? "").trim();
  const origin = (environment.PAPYRUS_CONSOLE_ORIGIN ?? "").trim() || (environment.PAPYRUS_SITE_ORIGIN ?? "").trim();
  const basePath = (environment.newsroomBasePath ?? "").trim().replace(/\/+$/, "");
  const consoleUrl = HTTPS_ORIGIN_PATTERN.test(origin) && (basePath === "" || /^\/[a-z0-9/-]+$/.test(basePath)) ? `${origin}${basePath}` : "";
  return {
    ...(TENANT_ID_PATTERN.test(tenant) ? { tenant_id: tenant } : {}),
    ...(VERSION_PATTERN.test(version) ? { papyrus_version: version } : {}),
    ...(BUCKET_PATTERN.test(bucket) ? { media_bucket: bucket } : {}),
    ...(IDENTITY_POOL_PATTERN.test(pool) ? { identity_pool_id: pool } : {}),
    ...(consoleUrl ? { console_url: consoleUrl } : {}),
  };
}

export function handleSiteDocument(
  environment?: SiteDocumentEnvironment,
  readOutputs: () => SiteOutputs | null = () => {
    try {
      return readAmplifyOutputsFile() as SiteOutputs | null;
    } catch {
      return null; // an unreadable outputs file only means the file leaves these two values out
    }
  },
): NextResponse {
  // Spelled out so the build inlines the engine version (withPapyrus `env`) and the tenant comes from .env.production.
  const values = environment ?? {
    PAPYRUS_TENANT_ID: process.env.PAPYRUS_TENANT_ID,
    PAPYRUS_ENGINE_VERSION: process.env.PAPYRUS_ENGINE_VERSION,
    PAPYRUS_SITE_ORIGIN: process.env.PAPYRUS_SITE_ORIGIN,
    PAPYRUS_CONSOLE_ORIGIN: process.env.PAPYRUS_CONSOLE_ORIGIN,
    newsroomBasePath: getPublicNewsroomBasePath(),
  };
  return NextResponse.json(siteDocument(values, readOutputs()), { headers: { "cache-control": "public, max-age=300" } });
}
