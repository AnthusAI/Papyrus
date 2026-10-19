/**
 * The local preview stands in for the multi-tenant newsroom: choosing a publishing account in the account menu
 * switches which publication's content the preview shows. The choice is a cookie so server and browser agree.
 */
export const LOCAL_PREVIEW_TENANT_COOKIE = "papyrus-preview-tenant";
export const LOCAL_PREVIEW_DEFAULT_TENANT_ID = "preview-papyrus";

export type LocalPreviewTenant = { accountId: string; name: string; role: string; fixtureHeadlineSet: number };

export const LOCAL_PREVIEW_TENANTS: readonly LocalPreviewTenant[] = [
  { accountId: LOCAL_PREVIEW_DEFAULT_TENANT_ID, name: "Papyrus", role: "publisher", fixtureHeadlineSet: 0 },
  { accountId: "preview-pilobolus", name: "Pilobolus", role: "editor", fixtureHeadlineSet: 1 },
];

export function previewTenantIdFromCookieHeader(cookieHeader: string | null | undefined): string {
  const match = cookieHeader?.split(";").map(part => part.trim()).find(part => part.startsWith(`${LOCAL_PREVIEW_TENANT_COOKIE}=`));
  const value = match ? decodeURIComponent(match.slice(LOCAL_PREVIEW_TENANT_COOKIE.length + 1)) : "";
  return LOCAL_PREVIEW_TENANTS.some(tenant => tenant.accountId === value) ? value : LOCAL_PREVIEW_DEFAULT_TENANT_ID;
}

export function getLocalPreviewTenantId(): string {
  return typeof document === "undefined" ? LOCAL_PREVIEW_DEFAULT_TENANT_ID : previewTenantIdFromCookieHeader(document.cookie);
}

export function setLocalPreviewTenantId(accountId: string): void {
  document.cookie = `${LOCAL_PREVIEW_TENANT_COOKIE}=${encodeURIComponent(accountId)}; path=/; max-age=31536000; samesite=lax`;
}
