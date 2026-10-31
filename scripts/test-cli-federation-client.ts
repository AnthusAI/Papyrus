import assert from "node:assert/strict";
import { App, SecretValue, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { UserPool, UserPoolIdentityProviderGoogle } from "aws-cdk-lib/aws-cognito";
import { CLI_LOOPBACK_CALLBACK as BACKEND_LOOPBACK, addProspectusGoogleOnlyClient, cliFederationClientCallbackUrls, prospectusSignInCallbackUrls } from "../amplify/auth/prospectus-google-client";
import { resolveSiteBackendFeatureFlags } from "../amplify/site-backend-names";
import { CLI_LOOPBACK_CALLBACK } from "../lib/cli-loopback-callback";

const redirectUrls = ["http://localhost:3000/", "https://newsroom.example.test/", "https://newsroom.example.test/newsroom"];
const identity = { brandId: "x", productionAppId: "", stagingAppId: "" } as never;

function synthesize(extraCallbackUrls?: readonly string[]) {
  const app = new App();
  const authStack = new Stack(app, "Auth", { env: { account: "111111111111", region: "us-east-1" } });
  const userPool = new UserPool(authStack, "UserPool");
  new UserPoolIdentityProviderGoogle(authStack, "Google", { userPool, clientId: "google-client", clientSecretValue: SecretValue.unsafePlainText("google-secret") });
  addProspectusGoogleOnlyClient(authStack, userPool, redirectUrls, extraCallbackUrls);
  return Template.fromStack(authStack);
}

const clientOf = (template: Template) => Object.values(template.findResources("AWS::Cognito::UserPoolClient"))[0] as { Properties: Record<string, unknown> };

const behaviours: Record<string, () => void> = {
  loopback_constants_agree() {
    assert.equal(BACKEND_LOOPBACK, CLI_LOOPBACK_CALLBACK);
  },
  flag_off_is_unchanged() {
    assert.equal(resolveSiteBackendFeatureFlags(undefined, {}, identity).cliOnFederationClient, false);
    assert.equal(resolveSiteBackendFeatureFlags({}, {}, { ...identity, productionAppId: "app" }).cliOnFederationClient, false, "off even on the legacy production pipeline");
    assert.deepEqual(cliFederationClientCallbackUrls(false, { PAPYRUS_SITE_ORIGIN: "https://newsroom.example.test" }), []);
    assert.deepEqual(synthesize().toJSON(), synthesize([]).toJSON(), "no extra callbacks synthesizes the same template");
    assert.deepEqual(clientOf(synthesize()).Properties.CallbackURLs, prospectusSignInCallbackUrls(redirectUrls));
  },
  flag_resolves_from_site_or_environment() {
    assert.equal(resolveSiteBackendFeatureFlags(undefined, { PAPYRUS_ENABLE_CLI_ON_FEDERATION_CLIENT: "true" }, identity).cliOnFederationClient, true);
    assert.equal(resolveSiteBackendFeatureFlags({ cliOnFederationClient: true }, {}, identity).cliOnFederationClient, true);
    assert.equal(resolveSiteBackendFeatureFlags({ cliOnFederationClient: false }, { PAPYRUS_ENABLE_CLI_ON_FEDERATION_CLIENT: "true" }, identity).cliOnFederationClient, false);
  },
  callback_list_is_exact() {
    const extra = cliFederationClientCallbackUrls(true, { PAPYRUS_SITE_ORIGIN: "https://newsroom.example.test" });
    assert.deepEqual(extra, [CLI_LOOPBACK_CALLBACK, "https://newsroom.example.test/cli/callback"]);
    const properties = clientOf(synthesize(extra)).Properties;
    assert.deepEqual(properties.CallbackURLs, [
      "http://localhost:3000/api/auth/prospectus/callback",
      "https://newsroom.example.test/api/auth/prospectus/callback",
      CLI_LOOPBACK_CALLBACK,
      "https://newsroom.example.test/cli/callback",
    ]);
    assert.deepEqual(properties.LogoutURLs, ["http://localhost:3000/", "https://newsroom.example.test/", "http://127.0.0.1:38947/"]);
    assert.throws(() => cliFederationClientCallbackUrls(true, {}), /PAPYRUS_SITE_ORIGIN/);
    assert.throws(() => cliFederationClientCallbackUrls(true, { PAPYRUS_SITE_ORIGIN: "http://insecure.example.test" }), /plain https origin/);
  },
  federation_client_is_google_only() {
    const properties = clientOf(synthesize(cliFederationClientCallbackUrls(true, { PAPYRUS_SITE_ORIGIN: "https://newsroom.example.test" }))).Properties;
    assert.deepEqual(properties.SupportedIdentityProviders, ["Google"]);
    assert.deepEqual(properties.AllowedOAuthFlows, ["code"]);
    assert.deepEqual(properties.ExplicitAuthFlows, ["ALLOW_REFRESH_TOKEN_AUTH"], "no password, SRP or custom auth is reachable");
    assert.equal(properties.GenerateSecret, false);
  },
};

const requested = process.argv[2];
if (requested) {
  if (!behaviours[requested]) throw new Error(`unknown behaviour ${requested}`);
  behaviours[requested]();
  console.log(JSON.stringify({ ok: true }));
} else {
  for (const run of Object.values(behaviours)) run();
  console.log("cli-federation-client ok");
}
