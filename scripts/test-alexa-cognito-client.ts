/**
 * The alexa plugin's Cognito app client for account linking (PPY-2a34d4). Run with no argument for everything, or with one
 * behaviour name (the Gherkin steps do this); each prints `{"behaviour": ...}`.
 */
import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CfnUserPoolDomain, CfnUserPoolIdentityProvider, UserPool } from "aws-cdk-lib/aws-cognito";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { resolveAlexaConfig } from "../amplify/plugins/alexa/config";
import { resolvePlugins } from "../amplify/plugins/registry";
import { wirePlugins } from "../amplify/plugins/wire";

const VENDOR_ID = "M2EXAMPLEVENDOR";
const env = { account: "123456789012", region: "us-east-1" };
const base = { name: "alexa", invocationName: "the example" };
const linked = { ...base, accountLinking: true, amazonVendorId: VENDOR_ID };

function wireFake(requests: Parameters<typeof resolvePlugins>[0], options: { google?: boolean } = {}) {
  const app = new App();
  const authStack = new Stack(app, "Auth", { env });
  const userPool = new UserPool(authStack, "Pool");
  if (options.google !== false) {
    new CfnUserPoolIdentityProvider(authStack, "GoogleProvider", { userPoolId: userPool.userPoolId, providerName: "Google", providerType: "Google", providerDetails: {} });
  }
  new CfnUserPoolDomain(authStack, "Domain", { userPoolId: userPool.userPoolId, domain: "papyrus-example-cms" });
  const dataStack = new Stack(app, "Data", { env });
  const lambda = new LambdaFunction(dataStack, "Skill", { runtime: Runtime.NODEJS_22_X, handler: "index.handler", code: Code.fromInline("x") });
  const contentActions = new LambdaFunction(dataStack, "ContentActions", { runtime: Runtime.PYTHON_3_12, handler: "handler.handler", code: Code.fromInline("x") });
  const outputs: any[] = [];
  const backend = {
    auth: { stack: authStack, resources: { userPool } },
    data: { resources: { graphqlApi: { apiId: "api" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://example.test/graphql" } } } },
    alexaSkill: { resources: { lambda } },
    addOutput: (value: unknown) => outputs.push(value),
    createStack: (name: string) => new Stack(app, name),
  };
  wirePlugins(backend, resolvePlugins(requests), contentActions, false);
  return { auth: Template.fromStack(authStack), data: Template.fromStack(dataStack), outputs };
}

const behaviours: Record<string, () => void> = {
  "the client exists only when account linking is on": () => {
    for (const request of [base, { ...base, accountLinking: false }]) {
      const { auth, data, outputs } = wireFake([request]);
      auth.resourceCountIs("AWS::Cognito::UserPoolClient", 0);
      assert.equal(JSON.stringify(data.toJSON()).includes("PAPYRUS_ALEXA_CLIENT_ID"), false);
      assert.equal(outputs.some((entry) => entry.custom?.alexa?.accountLinking !== undefined), false);
    }
    wireFake([linked]).auth.resourceCountIs("AWS::Cognito::UserPoolClient", 1);
  },

  "the vendor ID is required and checked": () => {
    assert.throws(() => resolveAlexaConfig({ ...base, accountLinking: true }), /amazonVendorId is required when accountLinking is true/);
    assert.throws(() => resolveAlexaConfig({ ...linked, amazonVendorId: "m2lowercase01" }), /amazonVendorId must be uppercase/);
    assert.throws(() => resolveAlexaConfig({ ...linked, amazonVendorId: "SHORT" }), /amazonVendorId must be uppercase/);
    assert.equal(resolveAlexaConfig(linked).amazonVendorId, VENDOR_ID);
  },

  "the client admits only Google and the code flow": () => {
    const { auth } = wireFake([linked]);
    const [client] = Object.values(auth.findResources("AWS::Cognito::UserPoolClient"));
    const properties = client.Properties;
    assert.deepEqual(properties.SupportedIdentityProviders, ["Google"]);
    assert.deepEqual(properties.AllowedOAuthFlows, ["code"]);
    assert.equal(properties.AllowedOAuthFlowsUserPoolClient, true);
    assert.deepEqual(properties.AllowedOAuthScopes, ["openid", "email", "profile"]);
    assert.deepEqual(properties.ExplicitAuthFlows, ["ALLOW_REFRESH_TOKEN_AUTH"]);
    assert.equal(properties.EnableTokenRevocation, true);
    assert.equal(properties.PreventUserExistenceErrors, "ENABLED");
    const google = Object.keys(auth.findResources("AWS::Cognito::UserPoolIdentityProvider"));
    assert.deepEqual(client.DependsOn, google, "the client waits for the Google provider");
  },

  "the client has a secret and long-lived refresh tokens": () => {
    const { auth } = wireFake([linked]);
    auth.hasResourceProperties("AWS::Cognito::UserPoolClient", {
      GenerateSecret: true,
      AccessTokenValidity: 60,
      IdTokenValidity: 60,
      RefreshTokenValidity: 365,
      TokenValidityUnits: { AccessToken: "minutes", IdToken: "minutes", RefreshToken: "days" },
    });
    assert.equal(JSON.stringify(auth.toJSON()).includes("SecretString"), false, "the secret is not stored anywhere");
    assert.equal(Object.keys(auth.findResources("AWS::SSM::Parameter")).length, 0);
    assert.equal(Object.keys(auth.findResources("AWS::SecretsManager::Secret")).length, 0);
  },

  "the callbacks are Amazon's redirect URLs for the vendor ID": () => {
    const { auth } = wireFake([linked]);
    auth.hasResourceProperties("AWS::Cognito::UserPoolClient", {
      CallbackURLs: [
        `https://pitangui.amazon.com/api/skill/link/${VENDOR_ID}`,
        `https://layla.amazon.com/api/skill/link/${VENDOR_ID}`,
        `https://alexa.amazon.co.jp/api/skill/link/${VENDOR_ID}`,
      ],
    });
  },

  "the function learns the pool and the client": () => {
    const { data } = wireFake([linked]);
    data.hasResourceProperties("AWS::Lambda::Function", {
      Environment: { Variables: Match.objectLike({ PAPYRUS_ALEXA_USER_POOL_ID: Match.anyValue(), PAPYRUS_ALEXA_CLIENT_ID: Match.anyValue() }) },
    });
  },

  "the outputs carry the linking settings beside the endpoint": () => {
    const { outputs } = wireFake([linked]);
    const alexa = outputs.map((entry) => entry.custom?.alexa).filter((entry) => entry !== undefined);
    assert.ok(alexa.some((entry) => entry.functionArn !== undefined));
    const accountLinking = alexa.find((entry) => entry.accountLinking !== undefined).accountLinking;
    assert.deepEqual(Object.keys(accountLinking).sort(), ["clientId", "hostedUiDomain", "userPoolId"]);
    assert.match(JSON.stringify(accountLinking.hostedUiDomain), /papyrus-example-cms.*\.auth\..*amazoncognito\.com/);
    // Amplify merges outputs deeply, so the two parts do not collide.
    const merged: any = {};
    for (const entry of alexa) Object.assign(merged, entry);
    assert.ok(merged.functionArn !== undefined && merged.accountLinking !== undefined);
  },

  "linking without Google is refused": () => {
    assert.throws(() => wireFake([linked], { google: false }), /no Google identity provider/);
  },
};

const requested = process.argv[2];
const names = requested === undefined ? Object.keys(behaviours) : [requested];
for (const name of names) {
  assert.ok(behaviours[name], `unknown behaviour "${name}"`);
  behaviours[name]();
  console.log(JSON.stringify({ behaviour: name }));
}
