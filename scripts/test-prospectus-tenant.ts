import assert from "node:assert/strict";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";
import { selectedTenantIdFromCookies } from "../lib/prospectus-tenant";
import { tenantIdForProspectusAccount } from "../lib/tenant-keys";

const secret = "x".repeat(48);
const farFuture = Math.floor(Date.now() / 1000) + 3600;

async function main() {
  assert.equal(tenantIdForProspectusAccount("Acct_Pilobol.us 01"), "acct-pilobol-us-01");
  assert.equal(tenantIdForProspectusAccount(""), undefined);
  assert.equal(tenantIdForProspectusAccount(null), undefined);

  const sealed = sealProspectusCookie(secret, PROSPECTUS_SESSION_COOKIE, { personId: "p1", accessToken: "t", accessTokenExpiresAt: farFuture, selectedAccountId: "Acct_Pilobol.us 01" }, farFuture);
  const cookies = { get: (name: string) => name === PROSPECTUS_SESSION_COOKIE ? { value: sealed } : undefined };
  assert.equal(await selectedTenantIdFromCookies(cookies, async () => secret), "acct-pilobol-us-01", "the selected account is the tenant");
  assert.equal(await selectedTenantIdFromCookies({ get: () => undefined }, async () => secret), undefined, "no session means no tenant");
  assert.equal(await selectedTenantIdFromCookies(cookies, async () => null), undefined, "a site without Prospectus has no tenant");
  assert.equal(await selectedTenantIdFromCookies(cookies, async () => "y".repeat(48)), undefined, "a cookie sealed with another secret is ignored");
  const unselected = sealProspectusCookie(secret, PROSPECTUS_SESSION_COOKIE, { personId: "p1", accessToken: "t", accessTokenExpiresAt: farFuture }, farFuture);
  assert.equal(await selectedTenantIdFromCookies({ get: () => ({ value: unselected }) }, async () => secret), undefined, "no selection means no tenant");
  console.log("prospectus tenant ok");
}
main();
