import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { CfnUserPoolIdentityProvider } from "aws-cdk-lib/aws-cognito";
import { defineBackend } from "@aws-amplify/backend";
import { applyGoogleEmailVerifiedMapping, defineSiteAuth } from "../amplify/auth/resource";
import { manageUserRole } from "../amplify/functions/manage-user-role/resource";

process.env.CDK_CONTEXT_JSON = JSON.stringify({
  "amplify-backend-name": "googleverifiedmappingtest",
  "amplify-backend-namespace": "googleverifiedmappingtest",
  "amplify-backend-type": "branch",
});

const app = new App();
const backend = defineBackend({
  auth: defineSiteAuth({ redirectUrls: ["http://localhost:3000/"] }),
  manageUserRole,
});
applyGoogleEmailVerifiedMapping(backend.auth.stack);

const template = Template.fromStack(backend.auth.stack);
const googleProviderEntry = Object.entries(template.findResources("AWS::Cognito::UserPoolIdentityProvider"))
  .find(([, resource]) => resource.Properties?.ProviderName === "Google");
const googleProvider = googleProviderEntry?.[1];
assert.ok(googleProvider, "the Google identity provider is synthesized");
assert.equal(googleProvider.Properties?.AttributeMapping?.email_verified, "email_verified");
assert.equal(googleProvider.Properties?.AttributeMapping?.email, "email", "existing email mapping is preserved");
const googleClients = Object.values(template.findResources("AWS::Cognito::UserPoolClient"))
  .filter((resource) => resource.Properties?.SupportedIdentityProviders?.some((provider: string | { Ref?: string }) =>
    typeof provider === "string" ? provider === "Google" : provider.Ref === googleProviderEntry?.[0]));
assert.ok(googleClients.length > 0, "at least one app client supports Google sign-in");
assert.ok(
  googleClients.every((resource) => {
    const writeAttributes = resource.Properties?.WriteAttributes;
    return writeAttributes === undefined || writeAttributes.includes("email_verified");
  }),
  "every Google-enabled app client can write the mapped verification claim",
);

assert.doesNotThrow(() => applyGoogleEmailVerifiedMapping(backend.auth.stack), "mapping application is idempotent");

const otherStack = new Stack(app, "UnrelatedProvider");
new CfnUserPoolIdentityProvider(otherStack, "OtherProvider", {
  userPoolId: "us-east-1_example",
  providerName: "Other",
  providerType: "OIDC",
  providerDetails: {},
  attributeMapping: { email: "mail" },
});
assert.throws(
  () => applyGoogleEmailVerifiedMapping(otherStack),
  /Expected exactly one Google identity provider/,
  "a pool without Google federation fails synthesis rather than silently omitting the mapping",
);

console.log("Google email_verified mapping synth: ok");
