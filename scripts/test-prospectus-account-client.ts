import assert from "node:assert/strict";
import { loadProspectusAccountState, prospectusSignInUrl, selectProspectusAccount } from "../lib/prospectus-account-client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

async function main() {
  assert.equal(prospectusSignInUrl("/newsroom?tab=board"), "/api/auth/prospectus/sign-in?returnTo=%2Fnewsroom%3Ftab%3Dboard");

  assert.deepEqual(
    await loadProspectusAccountState("/newsroom", async () => jsonResponse({ error: "unavailable" }, 503)),
    { status: "unavailable" },
    "a site without Prospectus configured shows nothing",
  );
  assert.deepEqual(
    await loadProspectusAccountState("/newsroom", async () => { throw new Error("offline"); }),
    { status: "unavailable" },
  );
  assert.deepEqual(
    await loadProspectusAccountState("/newsroom", async () => jsonResponse({ signedIn: false })),
    { status: "signedOut", signInUrl: "/api/auth/prospectus/sign-in?returnTo=%2Fnewsroom" },
  );
  assert.deepEqual(
    await loadProspectusAccountState("/newsroom", async () =>
      jsonResponse({ signedIn: true, publishingAccounts: [{ accountId: "a1", role: "member" }], selectedAccountId: "a1", cyclotronLabAccess: true }),
    ),
    { status: "signedIn", publishingAccounts: [{ accountId: "a1", role: "member" }], selectedAccountId: "a1", cyclotronLabAccess: true },
  );

  const requests: Array<{ input: string; init?: RequestInit }> = [];
  const selected = await selectProspectusAccount("a1", async (input, init) => {
    requests.push({ input, init });
    return jsonResponse({ selectedAccountId: "a1", role: "member" });
  });
  assert.deepEqual(selected, { selectedAccountId: "a1", role: "member" });
  assert.equal(requests[0].input, "/api/auth/prospectus/selection");
  assert.equal(requests[0].init?.body, JSON.stringify({ accountId: "a1" }));

  assert.deepEqual(
    await selectProspectusAccount("a2", async () => jsonResponse({ error: "not_a_publishing_account", message: "You cannot work on this site's publications in that account." }, 403)),
    { error: "You cannot work on this site's publications in that account." },
  );
  console.log("prospectus account client tests passed");
}

main();
