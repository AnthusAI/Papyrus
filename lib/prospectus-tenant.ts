import {
  PROSPECTUS_SESSION_COOKIE,
  loadProspectusSessionSealingSecret,
  openProspectusCookie,
  type ProspectusSignedInSession,
} from "./prospectus-session";
import { tenantIdForProspectusAccount } from "./tenant-keys";

type CookieReader = { get(name: string): { value: string } | undefined };

/**
 * The tenant of the publishing account the signed-in person selected, read from the sealed Prospectus session
 * cookie. Returns undefined on a site without Prospectus, with no session, or with no account selected, so the
 * caller falls back to the site's own tenant (PAPYRUS_TENANT_ID).
 */
export async function selectedTenantIdFromCookies(cookies: CookieReader, loadSecret: () => Promise<string | null> = loadProspectusSessionSealingSecret): Promise<string | undefined> {
  const sealingSecret = await loadSecret();
  if (!sealingSecret) return undefined;
  const session = openProspectusCookie<ProspectusSignedInSession>(sealingSecret, PROSPECTUS_SESSION_COOKIE, cookies.get(PROSPECTUS_SESSION_COOKIE)?.value);
  if (!session || session.accessTokenExpiresAt * 1000 <= Date.now()) return undefined;
  return tenantIdForProspectusAccount(session.selectedAccountId);
}
