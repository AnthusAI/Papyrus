import { NextResponse } from "next/server";

/**
 * What the CLI may know about a site besides how to sign in, served at `/.well-known/papyrus-site.json`: the site's tenant id
 * (only when it has one) and the Papyrus version it runs. It is a second file on purpose. `papyrus-cli.json` is read strictly by
 * every installed CLI and refuses unknown fields, so nothing may be added there. A CLI that has never heard of this file simply
 * never asks for it. Both values are public and neither is a credential: the tenant scopes requests and authorizes nothing.
 */
export const SITE_DOCUMENT_PATH = "/.well-known/papyrus-site.json";

export interface SiteDocument {
  /** The site's PAPYRUS_TENANT_ID build variable; absent for a site with no tenant. */
  tenant_id?: string;
  /** The @anthusai/papyrus version the site was built with; absent when it cannot be told (a checkout of the engine). */
  papyrus_version?: string;
}

export interface SiteDocumentEnvironment {
  PAPYRUS_TENANT_ID?: string;
  PAPYRUS_ENGINE_VERSION?: string;
}

const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;
const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]{1,40})?$/;

export function siteDocument(environment: SiteDocumentEnvironment): SiteDocument {
  const tenant = (environment.PAPYRUS_TENANT_ID ?? "").trim();
  const version = (environment.PAPYRUS_ENGINE_VERSION ?? "").trim();
  return {
    ...(TENANT_ID_PATTERN.test(tenant) ? { tenant_id: tenant } : {}),
    ...(VERSION_PATTERN.test(version) ? { papyrus_version: version } : {}),
  };
}

export function handleSiteDocument(environment?: SiteDocumentEnvironment): NextResponse {
  // Spelled out so the build inlines the engine version (withPapyrus `env`) and the tenant comes from .env.production.
  const values = environment ?? { PAPYRUS_TENANT_ID: process.env.PAPYRUS_TENANT_ID, PAPYRUS_ENGINE_VERSION: process.env.PAPYRUS_ENGINE_VERSION };
  return NextResponse.json(siteDocument(values), { headers: { "cache-control": "public, max-age=300" } });
}
