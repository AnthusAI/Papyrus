import type { ProspectusDirectoryAccount, ProspectusRole } from "./prospectus-site-identity";

/**
 * What a person may do on this site's publications, decided by Papyrus from the
 * role Prospectus gives them on an account, never more than that role allows.
 * An account publishes on this site when its `papyrus-<siteId>` product is
 * active. For now every member gets their role's capabilities on all of the
 * account's publications (Ryan, 2026-10-17: role now, per-person grants later);
 * src/papyrus_content/prospectus_publication_access.py applies the same table
 * where the curation tools run.
 */
export type PublicationCapability = "read" | "review" | "decide" | "steer";

export const PROSPECTUS_ROLE_PUBLICATION_CAPABILITIES: Record<ProspectusRole, readonly PublicationCapability[]> = {
  viewer: ["read"],
  member: ["read", "review", "decide"],
  admin: ["read", "review", "decide", "steer"],
  owner: ["read", "review", "decide", "steer"],
};

export const PROSPECTUS_SITE_PRODUCT_ENV = "PAPYRUS_PROSPECTUS_SITE_PRODUCT";

export interface PublishingAccountAccess {
  accountId: string;
  accountName: string;
  role: ProspectusRole;
  publicationCapabilities: PublicationCapability[];
}

export function publicationCapabilitiesForProspectusRole(role: string): PublicationCapability[] {
  return [...(PROSPECTUS_ROLE_PUBLICATION_CAPABILITIES[role as ProspectusRole] ?? [])];
}

export function prospectusSiteProduct(environment: Record<string, string | undefined> = process.env): string | null {
  const siteProduct = environment[PROSPECTUS_SITE_PRODUCT_ENV]?.trim();
  return siteProduct && siteProduct.startsWith("papyrus-") ? siteProduct : null;
}

export function publishingAccountsForSite(
  accounts: readonly ProspectusDirectoryAccount[],
  siteProduct: string | null,
): PublishingAccountAccess[] {
  if (!siteProduct) return [];
  return accounts
    .filter((account) => account.products.some((product) => product.product === siteProduct && product.status === "active"))
    .map((account) => ({
      accountId: account.id,
      accountName: account.name,
      role: account.role,
      publicationCapabilities: publicationCapabilitiesForProspectusRole(account.role),
    }))
    .filter((access) => access.publicationCapabilities.length > 0);
}
