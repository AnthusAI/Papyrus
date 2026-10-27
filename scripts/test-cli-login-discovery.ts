import assert from "node:assert/strict";
import { App, SecretValue, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { UserPool, UserPoolIdentityProviderGoogle } from "aws-cdk-lib/aws-cognito";
import { NextRequest } from "next/server";
import { addCliNativeClient } from "../amplify/auth/cli-native-client";
import { handleCliLoginDiscovery, type AmplifyOutputsForCliLogin } from "../lib/cli-login-discovery";

const site = "https://shipped.example.test";
const configured: AmplifyOutputsForCliLogin = {
  auth: { user_pool_id: "us-east-1_Synthetic", aws_region: "us-east-1", oauth: { domain: "shipped.auth.us-east-1.amazoncognito.com" } },
  data: { url: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql" },
  custom: { cliLogin: { clientId: "synthetic-cli-client", callbackUri: "http://localhost:5182/oauth/callback", refreshLifetimeSeconds: 2592000 } },
};

async function serve(outputs: AmplifyOutputsForCliLogin | null, environment: Record<string, string | undefined>, url = "http://internal.invalid/.well-known/papyrus-cli.json") {
  const response = handleCliLoginDiscovery(new NextRequest(url), { readOutputs: () => outputs, environment });
  return { status: response.status, cache: response.headers.get("cache-control"), body: await response.json() as Record<string, unknown> };
}

function client(refreshTokenValidityDays?: number, callbackUri = "http://localhost:5182/oauth/callback") {
  const stack = new Stack(new App(), "Auth");
  const pool = new UserPool(stack, "Pool");
  new UserPoolIdentityProviderGoogle(stack, "Google", { userPool: pool, clientId: "g", clientSecretValue: SecretValue.unsafePlainText("s") });
  addCliNativeClient(stack, pool, { callbackUri, refreshTokenValidityDays });
  const resources = Template.fromStack(stack).findResources("AWS::Cognito::UserPoolClient");
  const properties = Object.values(resources).map((r) => r.Properties as Record<string, unknown>);
  return properties.find((p) => p.ClientName === "papyrus-cli-native")!;
}

const behaviours: Record<string, () => Promise<unknown>> = {
  async published() {
    const result = await serve(configured, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, {
      publication: site,
      issuer: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Synthetic",
      client_id: "synthetic-cli-client",
      oauth_domain: "https://shipped.auth.us-east-1.amazoncognito.com",
      graphql_endpoint: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql",
      callback_uri: "http://localhost:5182/oauth/callback",
      refresh_lifetime_seconds: 2592000,
    });
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
  async no_client() {
    const result = await serve({ ...configured, custom: { cliLogin: null } }, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 404);
    assert.equal(result.body.error, "cli_login_not_configured");
    return result;
  },
  async unsafe_callback() {
    const bad = { ...configured, custom: { cliLogin: { clientId: "c", callbackUri: "https://evil.example.test/cb" } } };
    const result = await serve(bad, { PAPYRUS_SITE_ORIGIN: site });
    assert.equal(result.status, 404);
    return result;
  },
  async only_public_fields() {
    const result = await serve(configured, { PAPYRUS_SITE_ORIGIN: site });
    const allowed = ["publication", "issuer", "client_id", "oauth_domain", "graphql_endpoint", "callback_uri", "refresh_lifetime_seconds"];
    assert.deepEqual(Object.keys(result.body).sort(), [...allowed].sort());
    return result;
  },
  async client_shape() {
    const properties = client();
    assert.equal(properties.GenerateSecret, false);
    assert.deepEqual(properties.SupportedIdentityProviders, ["Google"]);
    assert.deepEqual(properties.AllowedOAuthFlows, ["code"]);
    assert.deepEqual(properties.CallbackURLs, ["http://localhost:5182/oauth/callback"]);
    assert.deepEqual(properties.ExplicitAuthFlows, ["ALLOW_REFRESH_TOKEN_AUTH"]);
    assert.equal(properties.EnableTokenRevocation, true);
    assert.equal(properties.RefreshTokenValidity, 30);
    assert.equal(client(7).RefreshTokenValidity, 7);
    return properties;
  },
  async client_refuses_unsafe_callback() {
    for (const callbackUri of ["https://evil.example.test/cb", "http://example.test:5182/cb", "http://localhost/cb", "http://localhost:80/cb", "http://user@localhost:5182/cb", "not a url"]) {
      assert.throws(() => client(undefined, callbackUri), /callbackUri/);
    }
    return { refused: true };
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
