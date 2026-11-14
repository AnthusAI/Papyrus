import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { handleCliLoginDiscovery, type AmplifyOutputsForCliLogin } from "../lib/cli-login-discovery";

const site = "https://shipped.example.test";
const configured: AmplifyOutputsForCliLogin = {
  auth: {
    user_pool_id: "us-east-1_Synthetic", user_pool_client_id: "synthetic-web-client", aws_region: "us-east-1",
    oauth: { domain: "shipped.auth.us-east-1.amazoncognito.com", redirect_sign_in_uri: ["https://shipped.example.test/", "http://localhost:3001/"] },
  },
  data: { url: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql" },
};

async function serve(outputs: AmplifyOutputsForCliLogin | null, environment: Record<string, string | undefined>, url = "http://internal.invalid/.well-known/papyrus-cli.json") {
  const response = handleCliLoginDiscovery(new NextRequest(url), { readOutputs: () => outputs, environment });
  return { status: response.status, cache: response.headers.get("cache-control"), body: await response.json() as Record<string, unknown> };
}

const federated: AmplifyOutputsForCliLogin = {
  ...configured,
  auth: { ...configured.auth, oauth: { ...configured.auth!.oauth, redirect_sign_in_uri: ["https://shipped.example.test/"] } },
  custom: {
    cliOnFederationClient: true,
    prospectusSignIn: { clientId: "synthetic-federation-client", callbackPath: "/api/auth/prospectus/callback" },
    cliLogin: { brokerEndpoint: "https://synthetic.lambda-url.us-east-1.on.aws/", remoteCallbackUri: "https://shipped.example.test/cli/callback" },
  },
};

const behaviours: Record<string, () => Promise<unknown>> = {
  async published() {
    const result = await serve(configured, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, {
      publication: site,
      issuer: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Synthetic",
      client_id: "synthetic-web-client",
      oauth_domain: "https://shipped.auth.us-east-1.amazoncognito.com",
      graphql_endpoint: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql",
      callback_uri: "http://localhost:3001/",
    });
    return result;
  },
  async flag_off_names_main_client() {
    const withUnusedFederation = { ...configured, custom: { prospectusSignIn: { clientId: "synthetic-federation-client", callbackPath: "/api/auth/prospectus/callback" } } };
    const result = await serve(withUnusedFederation, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 200);
    assert.equal(result.body.client_id, "synthetic-web-client");
    assert.equal(result.body.callback_uri, "http://localhost:3001/");
    assert.deepEqual(result.body, (await serve(configured, { PAPYRUS_SITE_ORIGIN: site })).body, "byte-identical to a site that never heard of the flag");
    return result;
  },
  async flag_on_names_federation_client() {
    const result = await serve(federated, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 200);
    assert.equal(result.body.client_id, "synthetic-federation-client");
    assert.equal(result.body.callback_uri, "http://127.0.0.1:38947/cli/callback");
    assert.equal(result.body.remote_callback_uri, "https://shipped.example.test/cli/callback");
    assert.equal(result.body.broker_endpoint, "https://synthetic.lambda-url.us-east-1.on.aws/");
    return result;
  },
  async flag_on_without_federation_client() {
    const result = await serve({ ...federated, custom: { cliOnFederationClient: true } }, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 404, "never fall back to the main client once the flag is on");
    return result;
  },
  async origin_is_configured_not_requested() {
    const result = await serve(configured, { PAPYRUS_SITE_ORIGIN: site }, "https://attacker.example.test/.well-known/papyrus-cli.json");
    assert.equal(result.body.publication, site);
    return result;
  },
  async origin_missing() {
    const result = await serve(configured, {});
    assert.equal(result.status, 503);
    return result;
  },
  async callback_not_registered() {
    const outputs = { ...configured, auth: { ...configured.auth, oauth: { ...configured.auth!.oauth, redirect_sign_in_uri: ["https://shipped.example.test/"] } } };
    const result = await serve(outputs, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 404);
    assert.equal(result.body.error, "cli_login_not_configured");
    return result;
  },
  async no_oauth_outputs() {
    const result = await serve({ data: configured.data }, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 404);
    return result;
  },
  async only_public_fields() {
    const result = await serve(configured, { PAPYRUS_SITE_ORIGIN: site });
    const allowed = ["publication", "issuer", "client_id", "oauth_domain", "graphql_endpoint", "callback_uri"];
    assert.deepEqual(Object.keys(result.body).sort(), [...allowed].sort());
    return result;
  },
};

async function main() {
  const requested = process.argv[2];
  if (requested) {
    if (!behaviours[requested]) throw new Error(`unknown behaviour ${requested}`);
    console.log(JSON.stringify(await behaviours[requested]()));
    return;
  }
  for (const run of Object.values(behaviours)) await run();
  console.log("cli-login-discovery ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
