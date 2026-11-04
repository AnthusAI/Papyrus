import { NextResponse } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";

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
}

/** The parts of the site's amplify_outputs.json this file reads. */
export interface SiteOutputs {
  storage?: { bucket_name?: string };
  auth?: { identity_pool_id?: string };
}

export interface SiteDocumentEnvironment {
  PAPYRUS_TENANT_ID?: string;
  PAPYRUS_ENGINE_VERSION?: string;
}

const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;
const BUCKET_PATTERN = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;
const IDENTITY_POOL_PATTERN = /^[a-z]{2}(?:-[a-z]+)+-\d:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]{1,40})?$/;

export function siteDocument(environment: SiteDocumentEnvironment, outputs: SiteOutputs | null = null): SiteDocument {
  const tenant = (environment.PAPYRUS_TENANT_ID ?? "").trim();
  const version = (environment.PAPYRUS_ENGINE_VERSION ?? "").trim();
  const bucket = (outputs?.storage?.bucket_name ?? "").trim();
  const pool = (outputs?.auth?.identity_pool_id ?? "").trim();
  return {
    ...(TENANT_ID_PATTERN.test(tenant) ? { tenant_id: tenant } : {}),
    ...(VERSION_PATTERN.test(version) ? { papyrus_version: version } : {}),
    ...(BUCKET_PATTERN.test(bucket) ? { media_bucket: bucket } : {}),
    ...(IDENTITY_POOL_PATTERN.test(pool) ? { identity_pool_id: pool } : {}),
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
  const values = environment ?? { PAPYRUS_TENANT_ID: process.env.PAPYRUS_TENANT_ID, PAPYRUS_ENGINE_VERSION: process.env.PAPYRUS_ENGINE_VERSION };
  return NextResponse.json(siteDocument(values, readOutputs()), { headers: { "cache-control": "public, max-age=300" } });
}
