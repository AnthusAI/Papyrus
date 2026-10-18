import assert from "node:assert/strict";
import { createProspectusAccount, loadProspectusAccountState, prospectusSignInUrl, selectProspectusAccount } from "../lib/prospectus-account-client";

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
  const created: Array<{ input: string; init?: RequestInit }> = [];
  assert.deepEqual(
    await createProspectusAccount("  Ryan's desk ", async (input, init) => {
      created.push({ input, init });
      return jsonResponse({ selectedAccountId: "new-account", role: "owner" }, 201);
    }, "key-1"),
    { selectedAccountId: "new-account", role: "owner" },
  );
  assert.equal(created[0].input, "/api/auth/prospectus/accounts");
  assert.equal(created[0].init?.method, "POST");
  assert.equal(created[0].init?.body, JSON.stringify({ name: "Ryan's desk", idempotencyKey: "key-1" }));
  assert.equal(JSON.parse(String((await (async () => { const sent: string[] = []; await createProspectusAccount("", async (_input, init) => { sent.push(String(init?.body)); return jsonResponse({ selectedAccountId: "x" }); }); return sent; })())[0])).name, undefined, "a blank name is not sent");
  assert.deepEqual(
    await createProspectusAccount("x", async () => jsonResponse({ message: "You already have a publishing account." }, 409)),
    { error: "You already have a publishing account." },
  );
  assert.deepEqual(
    await createProspectusAccount("x", async () => { throw new Error("offline"); }),
    { error: "The publishing account could not be created. Check your connection and try again." },
  );
  console.log("prospectus account client tests passed");
}

main();
