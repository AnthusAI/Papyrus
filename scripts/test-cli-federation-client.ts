import assert from "node:assert/strict";
import { App, SecretValue, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { CfnIdentityPool, CfnIdentityPoolRoleAttachment, UserPool, UserPoolIdentityProviderGoogle } from "aws-cdk-lib/aws-cognito";
import { CLI_FEDERATION_REFRESH_TOKEN_VALIDITY_DAYS, CLI_LOOPBACK_CALLBACK as BACKEND_LOOPBACK, addProspectusGoogleOnlyClient, cliFederationClientCallbackUrls, prospectusSignInCallbackUrls, trustClientOnIdentityPool } from "../amplify/auth/prospectus-google-client";
import { resolveSiteBackendFeatureFlags } from "../amplify/site-backend-names";
import { CLI_LOOPBACK_CALLBACK } from "../lib/cli-loopback-callback";

const redirectUrls = ["http://localhost:3000/", "https://newsroom.example.test/", "https://newsroom.example.test/newsroom"];
const identity = { amplifyAppId: "app", brandId: "x", productionAppId: "" } as Parameters<typeof resolveSiteBackendFeatureFlags>[2];

function synthesize(extraCallbackUrls?: readonly string[], refreshTokenValidityDays?: number) {
  const app = new App();
  const authStack = new Stack(app, "Auth", { env: { account: "111111111111", region: "us-east-1" } });
  const userPool = new UserPool(authStack, "UserPool");
  new UserPoolIdentityProviderGoogle(authStack, "Google", { userPool, clientId: "google-client", clientSecretValue: SecretValue.unsafePlainText("google-secret") });
  addProspectusGoogleOnlyClient(authStack, userPool, redirectUrls, extraCallbackUrls, refreshTokenValidityDays);
  return Template.fromStack(authStack);
}

const clientOf = (template: Template) => Object.values(template.findResources("AWS::Cognito::UserPoolClient"))[0] as { Properties: Record<string, unknown> };

/** An identity pool shaped as Amplify's defineAuth builds it: the web client as the one provider, one Token role mapping. */
function identityPoolStack(trustFederationClient: boolean) {
  const app = new App();
  const authStack = new Stack(app, "Auth", { env: { account: "111111111111", region: "us-east-1" } });
  const userPool = new UserPool(authStack, "UserPool");
  const webClient = userPool.addClient("WebClient");
  const providerName = `cognito-idp.us-east-1.amazonaws.com/${userPool.userPoolId}`;
  const pool = new CfnIdentityPool(authStack, "IdentityPool", {
    allowUnauthenticatedIdentities: true,
    cognitoIdentityProviders: [{ clientId: webClient.userPoolClientId, providerName, serverSideTokenCheck: false }],
  });
  const attachment = new CfnIdentityPoolRoleAttachment(authStack, "RoleAttachment", {
    identityPoolId: pool.ref,
    roles: { authenticated: "arn:aws:iam::111111111111:role/authenticated" },
    roleMappings: {
      mapping: { type: "Token", ambiguousRoleResolution: "AuthenticatedRole", identityProvider: `${providerName}:${webClient.userPoolClientId}` },
    },
  });
  const federationClient = addProspectusGoogleOnlyClient(authStack, userPool, redirectUrls, [CLI_LOOPBACK_CALLBACK]);
  if (trustFederationClient) trustClientOnIdentityPool(pool, attachment, federationClient.ref);
  return Template.fromStack(authStack);
}

const behaviours: Record<string, () => void> = {
  identity_pool_trusts_the_cli_client_like_the_web_client() {
    const template = identityPoolStack(true);
    const pool = Object.values(template.findResources("AWS::Cognito::IdentityPool"))[0] as { Properties: { CognitoIdentityProviders: Record<string, unknown>[] } };
    const providers = pool.Properties.CognitoIdentityProviders;
    assert.equal(providers.length, 2, "the web client and the federation client");
    assert.deepEqual(providers[1].ProviderName, providers[0].ProviderName, "same user pool");
    assert.equal(providers[1].ServerSideTokenCheck, providers[0].ServerSideTokenCheck, "same token check as the web client");
    assert.notDeepEqual(providers[1].ClientId, providers[0].ClientId);
    const attachment = Object.values(template.findResources("AWS::Cognito::IdentityPoolRoleAttachment"))[0] as { Properties: { RoleMappings: Record<string, Record<string, unknown>> } };
    const mappings = Object.values(attachment.Properties.RoleMappings);
    assert.equal(mappings.length, 2, "each client has its own role mapping, or it would fall to the default authenticated role");
    assert.equal(mappings[1].Type, "Token", "the group's role (editor, admin) decides the role, as for the browser");
    assert.equal(mappings[1].AmbiguousRoleResolution, mappings[0].AmbiguousRoleResolution);
    assert.notDeepEqual(mappings[1].IdentityProvider, mappings[0].IdentityProvider);
  },
  identity_pool_is_unchanged_without_the_cli_client() {
    const template = identityPoolStack(false);
    const pool = Object.values(template.findResources("AWS::Cognito::IdentityPool"))[0] as { Properties: { CognitoIdentityProviders: unknown[] } };
    assert.equal(pool.Properties.CognitoIdentityProviders.length, 1);
    const attachment = Object.values(template.findResources("AWS::Cognito::IdentityPoolRoleAttachment"))[0] as { Properties: { RoleMappings: Record<string, unknown> } };
    assert.equal(Object.keys(attachment.Properties.RoleMappings).length, 1);
  },

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
    assert.deepEqual(properties.LogoutURLs, ["http://localhost:3000/", "https://newsroom.example.test/"], "the loopback is a sign-in return only, never a logout URL");
    assert.throws(() => cliFederationClientCallbackUrls(true, {}), /PAPYRUS_SITE_ORIGIN/);
    assert.throws(() => cliFederationClientCallbackUrls(true, { PAPYRUS_SITE_ORIGIN: "http://insecure.example.test" }), /plain https origin/);
  },
  sessions_last_seven_days_only_when_moved() {
    const off = clientOf(synthesize()).Properties;
    assert.equal(off.RefreshTokenValidity, 60, "off: exactly as registered with Prospectus today");
    assert.equal((off.TokenValidityUnits as Record<string, string>).RefreshToken, "minutes");
    const on = clientOf(synthesize([CLI_LOOPBACK_CALLBACK], CLI_FEDERATION_REFRESH_TOKEN_VALIDITY_DAYS)).Properties;
    assert.equal(on.RefreshTokenValidity, 7);
    assert.deepEqual(on.TokenValidityUnits, { AccessToken: "minutes", IdToken: "minutes", RefreshToken: "days" });
    assert.equal(on.AccessTokenValidity, 60);
    assert.equal(on.IdTokenValidity, 60);
  },
  console_origin_is_used_when_set() {
    const environment = { PAPYRUS_SITE_ORIGIN: "https://shipped.example.test", PAPYRUS_CONSOLE_ORIGIN: "https://newsroom.shipped.example.test" };
    const extra = cliFederationClientCallbackUrls(true, environment);
    assert.deepEqual(extra, [CLI_LOOPBACK_CALLBACK, "https://newsroom.shipped.example.test/cli/callback"]);
    const consoleRedirectUrls = ["http://localhost:3000/", "https://shipped.example.test/", "https://newsroom.shipped.example.test/"];
    const app = new App();
    const authStack = new Stack(app, "Auth", { env: { account: "111111111111", region: "us-east-1" } });
    const userPool = new UserPool(authStack, "UserPool");
    new UserPoolIdentityProviderGoogle(authStack, "Google", { userPool, clientId: "google-client", clientSecretValue: SecretValue.unsafePlainText("google-secret") });
    addProspectusGoogleOnlyClient(authStack, userPool, consoleRedirectUrls, extra);
    const callbacks = clientOf(Template.fromStack(authStack)).Properties.CallbackURLs as string[];
    assert.ok(callbacks.includes("https://newsroom.shipped.example.test/api/auth/prospectus/callback"), "the Prospectus web callback follows the console redirect URL");
    assert.ok(callbacks.includes("https://newsroom.shipped.example.test/cli/callback"));
    assert.ok(callbacks.includes(CLI_LOOPBACK_CALLBACK));
    assert.ok(!callbacks.includes("https://shipped.example.test/cli/callback"), "the CLI callback is on the console, not the site origin");
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
