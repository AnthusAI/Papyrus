import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { resolvePlugins, KNOWN_PLUGINS } from "../amplify/plugins/registry";
import { signupSchemaDefinitions } from "../amplify/plugins/signup/schema";
import { resolveSignupConfig, signupManifest } from "../amplify/plugins/signup/papyrus.plugin";
import { addSignupRateLimit, SIGNUP_MUTATION_FIELD } from "../amplify/plugins/signup/waf";
import { wirePlugins, PLUGINS_OUTPUT_KEY } from "../amplify/plugins/wire";
import { schema } from "../amplify/data/schema";
import { editorialChecksSchemaDefinitions } from "../amplify/functions/editorial-checks/schema";
import { EDITORIAL_CHECKS_FUNCTION_FIELDS, editorialChecksSecretParameters } from "../amplify/functions/editorial-checks/wire";
import { EDITORIAL_CHECKS_TIMEOUT_SECONDS } from "../amplify/functions/editorial-checks/resource";
import { pluginSettings, signupForms } from "../lib/plugin-settings";
import { csvCell, neutralizeFormula, signupEntriesToCsv } from "../lib/signup-csv";

assert.deepEqual(resolvePlugins(undefined), []);
assert.deepEqual(resolvePlugins([]), []);
assert.throws(() => resolvePlugins(["newsletter"]), /Unknown plugin "newsletter"/);
assert.throws(() => resolvePlugins(["signup", { name: "signup" }]), /listed twice/);
assert.deepEqual(resolvePlugins(["signup"])[0].config, { forms: ["newsletter"], addressLimitPerMinute: 20, waf: true });
assert.deepEqual(
  resolvePlugins([{ name: "signup", forms: ["news", "events", "news"], addressLimitPerMinute: 30, waf: false }])[0].config,
  { forms: ["news", "events"], addressLimitPerMinute: 30, waf: false },
);

assert.throws(() => resolveSignupConfig({ name: "signup", forms: [] }), /non-empty list/);
assert.throws(() => resolveSignupConfig({ name: "signup", forms: ["Bad Name"] }), /lowercase names/);
assert.throws(() => resolveSignupConfig({ name: "signup", forms: ["x".repeat(41)] }), /lowercase names/);
assert.throws(() => resolveSignupConfig({ name: "signup", addressLimitPerMinute: 9 }), /from 10 to 1000/);
assert.throws(() => resolveSignupConfig({ name: "signup", addressLimitPerMinute: 1001 }), /from 10 to 1000/);
assert.throws(() => resolveSignupConfig({ name: "signup", waf: "yes" as unknown as boolean }), /waf must be a boolean/);
assert.throws(() => resolveSignupConfig({ name: "signup", webhook: "https://x.test" }), /Unknown signup plugin settings: webhook/);

const definitions = signupSchemaDefinitions() as Record<string, unknown>;
for (const name of [...signupManifest.models, ...signupManifest.mutations]) {
  assert.ok(name in definitions, `schema defines ${name}`);
}
assert.deepEqual(Object.keys(definitions).sort(), ["SignupEntry", "SignupReceipt", "submitSignup"]);
assert.deepEqual(signupManifest.guest.mutations, [SIGNUP_MUTATION_FIELD]);
assert.equal(KNOWN_PLUGINS.signup.manifest, signupManifest);

function wafTemplate(limit: number) {
  const stack = new Stack(new App(), "Protection", { env: { account: "123456789012", region: "us-east-1" } });
  addSignupRateLimit(stack, { graphqlApiArn: "arn:aws:appsync:us-east-1:123456789012:apis/abc123", limit });
  return Template.fromStack(stack);
}
const waf = wafTemplate(20);
waf.resourceCountIs("AWS::WAFv2::WebACL", 1);
waf.resourceCountIs("AWS::WAFv2::WebACLAssociation", 1);
waf.hasResourceProperties("AWS::WAFv2::WebACL", {
  Scope: "REGIONAL",
  DefaultAction: { Allow: {} },
  Rules: [
    Match.objectLike({
      Action: { Block: { CustomResponse: { ResponseCode: 429 } } },
      Statement: {
        RateBasedStatement: Match.objectLike({
          Limit: 20,
          EvaluationWindowSec: 60,
          AggregateKeyType: "IP",
          ScopeDownStatement: {
            ByteMatchStatement: Match.objectLike({
              SearchString: "submitSignup",
              FieldToMatch: { Body: { OversizeHandling: "NO_MATCH" } },
            }),
          },
        }),
      },
    }),
  ],
});
waf.hasResourceProperties("AWS::WAFv2::WebACLAssociation", { ResourceArn: "arn:aws:appsync:us-east-1:123456789012:apis/abc123" });
assert.throws(() => wafTemplate(9), /at least 10/);

const untouchedBackend = new Proxy({}, { get: () => assert.fail("a site without plugins must not touch the backend") });
wirePlugins(untouchedBackend, [], undefined as never);

const outputs = { custom: { [PLUGINS_OUTPUT_KEY]: { signup: { contract: 1, forms: ["news", "events"] } } } };
assert.deepEqual(pluginSettings(outputs, "signup"), { contract: 1, forms: ["news", "events"] });
assert.equal(pluginSettings(outputs, "other"), null);
assert.equal(pluginSettings({}, "signup"), null);
assert.equal(pluginSettings(null, "signup"), null);
assert.deepEqual(signupForms(outputs), ["news", "events"]);
assert.deepEqual(signupForms({}), []);

assert.equal(neutralizeFormula("=SUM(A1)"), "'=SUM(A1)");
assert.equal(neutralizeFormula("+1"), "'+1");
assert.equal(neutralizeFormula("-1"), "'-1");
assert.equal(neutralizeFormula("@cmd"), "'@cmd");
assert.equal(neutralizeFormula("reader@example.test"), "reader@example.test");
assert.equal(csvCell('say "hi", ok'), '"say ""hi"", ok"');
assert.equal(csvCell("line\nbreak"), '"line\nbreak"');
assert.equal(
  signupEntriesToCsv([
    { id: "1", form: "news", value: "reader@example.test", submittedAt: "2026-10-13T12:00:00.000Z" },
    { id: "2", form: "news", value: "=cmd@example.test", submittedAt: "2026-10-13T12:01:00.000Z" },
  ]),
  "form,value,submittedAt\r\nnews,reader@example.test,2026-10-13T12:00:00.000Z\r\nnews,'=cmd@example.test,2026-10-13T12:01:00.000Z\r\n",
);
assert.equal(signupEntriesToCsv([]), "form,value,submittedAt\r\n");

// Editorial checks are core, not a plugin: every site's base schema has them, and they cannot be requested as a plugin.
assert.throws(() => resolvePlugins(["editorial-checks"]), /Unknown plugin "editorial-checks"/);
assert.deepEqual(Object.keys(KNOWN_PLUGINS).sort(), ["reader-steering", "signup"]);
const baseSchemaText = schema.transform().schema;
for (const name of Object.keys(editorialChecksSchemaDefinitions)) {
  assert.ok(baseSchemaText.includes(name), `the base schema defines ${name}`);
}
assert.ok(EDITORIAL_CHECKS_TIMEOUT_SECONDS < 30, "the function must finish inside AppSync's 30 second resolver limit");
assert.deepEqual(
  EDITORIAL_CHECKS_FUNCTION_FIELDS.map((field) => field.split("/").pop()).sort(),
  [
    "createEditorialCheckRun", "createEditorialPolicy", "getEditorialCheckRun", "getEditorialCheckSettings", "getEditorialContext", "getItem",
    "listEditorialFeedbacks", "listEditorialPolicies", "listKnowledgeCorporaByRoleAndName", "updateEditorialCheckRun", "updateEditorialPolicy",
  ],
);

// The function reads its provider keys from SSM itself; it may read exactly those two names.
const secretArns = editorialChecksSecretParameters("us-east-1", "123456789012", "dabc123");
assert.ok(secretArns.includes("arn:aws:ssm:us-east-1:123456789012:parameter/amplify/dabc123/*/TYPESAFE_API_KEY"));
assert.ok(secretArns.includes("arn:aws:ssm:us-east-1:123456789012:parameter/amplify/shared/dabc123/OPENAI_API_KEY"));
assert.ok(secretArns.every((arn) => arn.endsWith("/TYPESAFE_API_KEY") || arn.endsWith("/OPENAI_API_KEY")));
assert.equal(editorialChecksSecretParameters("us-east-1", "123456789012", "").length, 4, "a sandbox gets only the sandbox paths");

console.log("plugins ok");
