/**
 * Drives the real Next curation route handlers against a live curation peer over loopback HTTP.
 * Used only by features_backend/newsroom_curation.feature. Prospectus is a synthetic transport;
 * everything between the sealed cookie and the peer is the production code.
 * Usage: tsx scripts/curation-routes-bdd-harness.ts <peer-port> <member|viewer>
 */
import { NextRequest } from "next/server";
import { handleCurationRoute, type CurationRoute } from "../lib/curation-routes";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";
import { ProspectusSiteAccounts } from "../lib/prospectus-site-identity";

const [port, role] = process.argv.slice(2);
const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const origin = "https://newsroom.example.test";
const account = "account-a";
const person = { id: "person-a", createdAt: "2026-01-01T00:00:00Z" };
const pins = { "x-cyclotron-account": account, "x-papyrus-publication": "demo-publication", "x-papyrus-binding": "binding-1" };
const nowInSeconds = Math.floor(Date.now() / 1000);
const cookie = `${PROSPECTUS_SESSION_COOKIE}=${sealProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE,
  { personId: person.id, accessToken: "synthetic-token", accessTokenExpiresAt: nowInSeconds + 600, selectedAccountId: account }, nowInSeconds + 600)}`;

const options = {
  upstreamUrl: `http://127.0.0.1:${port}`,
  publicationId: "demo-publication",
  siteProduct: "papyrus-synthetic",
  resolveRuntime: async () => ({
    accounts: new ProspectusSiteAccounts(async (request) => {
      if (request.path === "/v1/account-directory") return { person, accounts: [{ id: account, name: "A", role, products: [{ product: "papyrus-synthetic", status: "active" }] }] };
      if (request.path === "/v1/identities/me") return { person };
      return { allowed: true, accountId: account, personId: person.id, product: "papyrus-synthetic", role, operation: "console:read", revision: 1 };
    }),
    cognitoClient: { hostedUiOrigin: "https://h", userPoolId: "p", clientId: "c", redirectUri: `${origin}/cb` },
    sealingSecret,
  }),
};

async function call(route: CurationRoute, body?: unknown) {
  const request = new NextRequest(new URL(`/api/newsroom/curation/${route}`, origin), body === undefined
    ? { headers: { cookie } }
    : { method: "POST", headers: { cookie, origin, "content-type": "application/json", ...pins }, body: JSON.stringify(body) });
  const response = await handleCurationRoute(request, route, options);
  return { status: response.status, body: await response.json() };
}

async function main() {
  const refs = [{ id: "editor", revision: 1 }];
  const output = {
    context: await call("context"),
    status: await call("publication", { operation: "status", payload: {} }),
    contract: await call("priming", { query: "query($list:ID!,$refs:JSON!){primingContract(listId:$list,classifiers:$refs)}", variables: { list: "examples", refs } }),
    importAttempt: await call("priming", {
      query: "mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}",
      variables: { action: "transform", payload: { identifier: `import-${role}`, list_id: "examples", refs, transformer_id: "papyrus", inputs: { url: "https://example.invalid/paper" } } },
    }),
  };

  process.stdout.write(JSON.stringify(output));
}

main().catch((error) => {
  process.stderr.write(`${error?.stack ?? error}\n`);
  process.exit(1);
});
