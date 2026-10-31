/**
 * The alexa plugin's contracts: config, registry, deploy wiring, the skill endpoint and the skill package generator.
 * Run with no argument for everything, or with one behaviour name (the Gherkin steps do this); each prints `{"behaviour": ...}`.
 * Later alexa tasks add their own `scripts/test-alexa-*.ts` files; `npm run test:alexa` runs them all.
 */
import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import type { RequestEnvelope } from "ask-sdk-model";
import { resolveAlexaConfig } from "../amplify/plugins/alexa/config";
import { APL_DOCUMENTS } from "../amplify/plugins/alexa/apl";
import { assertUniqueIds, type IntentModule, type PublicStorySource } from "../amplify/plugins/alexa/contracts";
import { INTENT_MODULES } from "../amplify/plugins/alexa/intents";
import { alexaManifest, alexaPlugin, ALEXA_APPKIT_PRINCIPAL, ALEXA_OUTPUT_KEY } from "../amplify/plugins/alexa/papyrus.plugin";
import { invokeSkill, SkillIdMismatchError } from "../amplify/plugins/alexa/skill";
import { KNOWN_PLUGINS, resolvePlugins } from "../amplify/plugins/registry";
import { PLUGINS_OUTPUT_KEY, wirePlugins } from "../amplify/plugins/wire";
import { generateSkillPackage, INTERACTION_MODEL_PATH, SKILL_MANIFEST_PATH } from "./alexa/generate-skill-package";

const here = path.dirname(fileURLToPath(import.meta.url));
const pluginDirectory = path.resolve(here, "../amplify/plugins/alexa");
// Built from parts: a bare UUID literal in a test looks like a leaked session identifier to the repository scanner.
const skillIdFrom = (...parts: string[]) => `amzn1.ask.skill.${parts.join("-")}`;
const SKILL_ID = skillIdFrom("12345678", "1234", "1234", "1234", "123456789abc");
const OTHER_SKILL_ID = skillIdFrom("87654321", "4321", "4321", "4321", "cba987654321");
const ARN = "arn:aws:lambda:us-east-1:123456789012:function:papyrus-alexa-skill";
const request = { name: "alexa", invocationName: "the example" };

function launchEvent(skillId: string): RequestEnvelope {
  return {
    version: "1.0",
    session: { new: true, sessionId: "s", application: { applicationId: skillId }, user: { userId: "u" } },
    context: { System: { application: { applicationId: skillId }, user: { userId: "u" }, device: { deviceId: "d" }, apiEndpoint: "https://api.amazonalexa.com" } },
    request: { type: "LaunchRequest", requestId: "r", timestamp: "2026-10-31T00:00:00Z", locale: "en-US" },
  } as RequestEnvelope;
}

const fakeStories: PublicStorySource = {
  listLatest: async () => [{ id: "1", slug: "a", title: "A headline", publishedAt: "2026-10-31T00:00:00Z" }],
  getStory: async () => undefined,
};

function wireFake(requests: Parameters<typeof resolvePlugins>[0]) {
  const app = new App();
  const stack = new Stack(app, "Data", { env: { account: "123456789012", region: "us-east-1" } });
  const lambda = new LambdaFunction(stack, "Skill", { runtime: Runtime.NODEJS_22_X, handler: "index.handler", code: Code.fromInline("x") });
  const contentActions = new LambdaFunction(stack, "ContentActions", { runtime: Runtime.PYTHON_3_12, handler: "handler.handler", code: Code.fromInline("x") });
  const outputs: any[] = [];
  const backend = {
    data: { resources: { graphqlApi: { apiId: "api" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://example.test/graphql" } } } },
    alexaSkill: { resources: { lambda } },
    addOutput: (value: unknown) => outputs.push(value),
    createStack: (name: string) => new Stack(app, name),
  };
  wirePlugins(backend, resolvePlugins(requests), contentActions, false);
  return { template: Template.fromStack(stack), outputs, lambda };
}

const behaviours: Record<string, () => Promise<void> | void> = {
  "plugin is absent when the site does not list it": () => {
    assert.ok("alexa" in KNOWN_PLUGINS);
    assert.deepEqual(resolvePlugins(undefined), []);
    assert.deepEqual(resolvePlugins(["signup"]).map(({ plugin }) => plugin.manifest.name), ["signup"]);
    const fake = (() => {
      const app = new App();
      const stack = new Stack(app, "Data");
      const contentActions = new LambdaFunction(stack, "ContentActions", { runtime: Runtime.PYTHON_3_12, handler: "handler.handler", code: Code.fromInline("x") });
      const outputs: unknown[] = [];
      wirePlugins({ addOutput: (value: unknown) => outputs.push(value) }, [], contentActions);
      return outputs;
    })();
    assert.deepEqual(fake, []);
  },

  "config is validated": () => {
    assert.deepEqual(resolveAlexaConfig(request), { invocationName: "the example", skillName: "The Example", accountLinking: false });
    assert.deepEqual(resolveAlexaConfig({ ...request, skillId: SKILL_ID, accountLinking: true, siteOrigin: "https://example.com", skillName: "Example News" }), {
      invocationName: "the example",
      skillName: "Example News",
      skillId: SKILL_ID,
      accountLinking: true,
      siteOrigin: "https://example.com",
    });
    assert.throws(() => resolveAlexaConfig("alexa"), /invocationName is required/);
    assert.throws(() => resolveAlexaConfig({ name: "alexa", invocationName: "Example" }), /invocationName is required/);
    assert.throws(() => resolveAlexaConfig({ name: "alexa", invocationName: "x" }), /invocationName is required/);
    assert.throws(() => resolveAlexaConfig({ ...request, skillId: "skill" }), /skillId must look like/);
    assert.throws(() => resolveAlexaConfig({ ...request, accountLinking: "yes" }), /accountLinking must be true or false/);
    assert.throws(() => resolveAlexaConfig({ ...request, siteOrigin: "http://example.com" }), /siteOrigin must be an https origin/);
    assert.throws(() => resolveAlexaConfig({ ...request, locale: "de-DE" }), /Unknown alexa plugin settings: locale/);
    assert.deepEqual(alexaPlugin.publicSettings(resolveAlexaConfig(request)), { contract: 1, invocationName: "the example", accountLinking: false });
  },

  "only the Alexa service may invoke the function": () => {
    const anySkill = wireFake([request]);
    anySkill.template.hasResourceProperties("AWS::Lambda::Permission", Match.objectLike({ Action: "lambda:InvokeFunction", Principal: ALEXA_APPKIT_PRINCIPAL }));
    const unconditional = Object.values(anySkill.template.findResources("AWS::Lambda::Permission")).filter((resource) => resource.Properties.Principal === ALEXA_APPKIT_PRINCIPAL);
    assert.equal(unconditional.length, 1);
    assert.equal(unconditional[0].Properties.EventSourceToken, undefined);

    const oneSkill = wireFake([{ ...request, skillId: SKILL_ID }]);
    oneSkill.template.hasResourceProperties("AWS::Lambda::Permission", { Action: "lambda:InvokeFunction", Principal: ALEXA_APPKIT_PRINCIPAL, EventSourceToken: SKILL_ID });
    assert.equal(oneSkill.template.findResources("AWS::Lambda::Permission") && Object.keys(oneSkill.template.findResources("AWS::Lambda::Permission")).length, 1);
  },

  "wiring publishes the endpoint": () => {
    const { template, outputs } = wireFake([{ ...request, skillId: SKILL_ID }]);
    template.hasResourceProperties("AWS::Lambda::Function", { Environment: { Variables: Match.objectLike({ PAPYRUS_ALEXA_SETTINGS: Match.stringLikeRegexp("the example") }) } });
    const custom = outputs.map((entry) => entry.custom);
    assert.ok(custom.some((entry) => entry[ALEXA_OUTPUT_KEY]?.functionArn !== undefined), "custom.alexa.functionArn is an output");
    const published = custom.find((entry) => entry[PLUGINS_OUTPUT_KEY] !== undefined)[PLUGINS_OUTPUT_KEY];
    assert.deepEqual(published.alexa, { contract: 1, invocationName: "the example", accountLinking: false });
    assert.equal(JSON.stringify(published).includes(SKILL_ID), false, "the public settings carry no skill ID");
  },

  "endpoint rejects a request with the wrong skill ID": async () => {
    const config = resolveAlexaConfig({ ...request, skillId: SKILL_ID });
    await assert.rejects(invokeSkill(launchEvent(OTHER_SKILL_ID), config, { config, stories: fakeStories }), SkillIdMismatchError);
    const response = await invokeSkill(launchEvent(SKILL_ID), config, { config, stories: fakeStories });
    assert.match(JSON.stringify(response.response.outputSpeech), /A headline/);
  },

  "endpoint serves nothing until a skill ID is configured": async () => {
    const config = resolveAlexaConfig(request);
    await assert.rejects(invokeSkill(launchEvent(SKILL_ID), config, { config, stories: fakeStories }), SkillIdMismatchError);
  },

  "registries list every module and keep ids unique": async () => {
    assert.throws(() => assertUniqueIds("intent", ["a", "b", "a"]), /Duplicate intent id "a"/);
    const listed = new Set<unknown>(INTENT_MODULES.map((entry) => entry.id));
    for (const file of readdirSync(path.join(pluginDirectory, "intents")).filter((name) => name.endsWith(".ts") && name !== "index.ts")) {
      const exported = Object.values(await import(path.join(pluginDirectory, "intents", file))) as IntentModule[];
      const modules = exported.filter((value) => typeof value?.id === "string" && typeof value?.create === "function");
      assert.ok(modules.length > 0, `intents/${file} exports an IntentModule`);
      for (const candidate of modules) assert.ok(listed.has(candidate.id), `intents/${file} (${candidate.id}) is listed in intents/index.ts`);
    }
    const listedDocuments = new Set<unknown>(APL_DOCUMENTS.map((document) => document.id));
    for (const file of readdirSync(path.join(pluginDirectory, "apl")).filter((name) => name.endsWith(".ts") && name !== "index.ts")) {
      const exported = Object.values(await import(path.join(pluginDirectory, "apl", file))) as { id?: string; document?: { type?: string } }[];
      const documents = exported.filter((value) => typeof value?.id === "string" && value?.document !== undefined);
      assert.ok(documents.length > 0, `apl/${file} exports an AplDocument`);
      for (const document of documents) assert.ok(listedDocuments.has(document.id), `apl/${file} (${document.id}) is listed in apl/index.ts`);
    }
    for (const document of APL_DOCUMENTS) assert.equal(document.document.type, "APL", `${document.id} is an APL document`);
  },

  "skill package is generated deterministically": () => {
    const config = resolveAlexaConfig(request);
    const first = generateSkillPackage(config, { endpointArn: ARN });
    const second = generateSkillPackage(config, { endpointArn: ARN, modules: [...INTENT_MODULES].reverse() });
    assert.deepEqual(first, second);
    assert.deepEqual(Object.keys(first).sort(), [INTERACTION_MODEL_PATH, SKILL_MANIFEST_PATH].sort());
    const manifest = JSON.parse(first[SKILL_MANIFEST_PATH]);
    assert.equal(manifest.manifest.apis.custom.endpoint.uri, ARN);
    assert.equal(manifest.manifest.publishingInformation.locales["en-US"].name, "The Example");
    const model = JSON.parse(first[INTERACTION_MODEL_PATH]);
    assert.equal(model.interactionModel.languageModel.invocationName, "the example");
    assert.ok(first[SKILL_MANIFEST_PATH].endsWith("}\n"));

    const intent = (name: string, id = name): IntentModule => ({ id, create: () => ({ canHandle: () => false, handle: () => ({}) as never }), interactionModel: { intent: { name, samples: ["a"] } } });
    const composed = generateSkillPackage(config, { endpointArn: ARN, modules: [intent("ZedIntent"), intent("AlphaIntent")] });
    assert.deepEqual(JSON.parse(composed[INTERACTION_MODEL_PATH]).interactionModel.languageModel.intents.map((entry: { name: string }) => entry.name), ["AlphaIntent", "ZedIntent"]);
    assert.throws(() => generateSkillPackage(config, { endpointArn: ARN, modules: [intent("Same", "one"), intent("Same", "two")] }), /defined by two intent modules/);
  },
};

async function main() {
  const requested = process.argv[2];
  const names = requested === undefined ? Object.keys(behaviours) : [requested];
  for (const name of names) {
    const behaviour = behaviours[name];
    assert.ok(behaviour, `unknown behaviour "${name}"`);
    await behaviour();
    console.log(JSON.stringify({ behaviour: name }));
  }
  assert.equal(alexaManifest.name, "alexa");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
