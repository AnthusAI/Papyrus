import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { AmplifyDynamoDbTableWrapper } from "@aws-amplify/graphql-api-construct";
import { App, CfnResource, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { CfnTable } from "aws-cdk-lib/aws-dynamodb";
import { Architecture, Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { DEFAULT_DEBOUNCE_SECONDS, readProjectionFreshness, resolveHomePageConfig } from "../amplify/plugins/home-page/config";
import { HOME_PAGE_SNAPSHOT_TASK, homePageManifest, homePagePlugin, homePageStreamFilterPattern } from "../amplify/plugins/home-page/papyrus.plugin";
import { KNOWN_PLUGINS, resolvePlugins } from "../amplify/plugins/registry";
import { wirePlugins, PLUGINS_OUTPUT_KEY } from "../amplify/plugins/wire";

const account = "123456789012";
const environment = { account, region: "us-east-1" };

function siteDirectory(projection: object | undefined): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "home-page-plugin-"));
  if (projection !== undefined) fs.writeFileSync(path.join(directory, "projection.json"), JSON.stringify(projection));
  return directory;
}

type TableMode = "manager" | "cfn" | "cfn-generated-name";

function fakeBackend(mode: TableMode = "manager") {
  const app = new App();
  const dataStack = new Stack(app, "Data", { env: environment });
  let cfnTables: Record<string, CfnTable> = {};
  let amplifyDynamoDbTables: Record<string, AmplifyDynamoDbTableWrapper> = {};
  if (mode === "manager") {
    const resource = new CfnResource(dataStack, "ReferenceManaged", { type: "Custom::AmplifyDynamoDBTable", properties: { tableName: "Reference-test", billingMode: "PAY_PER_REQUEST" } });
    amplifyDynamoDbTables = { Reference: new AmplifyDynamoDbTableWrapper(resource) };
  } else {
    const reference = new CfnTable(dataStack, mode === "cfn" ? "Reference" : "ReferenceTable", {
      keySchema: [{ attributeName: "id", keyType: "HASH" }],
      attributeDefinitions: [{ attributeName: "id", attributeType: "S" }],
      billingMode: "PAY_PER_REQUEST",
    });
    cfnTables = mode === "cfn" ? { Reference: reference } : { SomeReferenceTable: reference, ReferenceTable: reference };
    if (mode === "cfn-generated-name") cfnTables = { ReferenceTable: reference };
  }
  const trigger = new LambdaFunction(dataStack, "Trigger", { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x") });
  const contentActions = new LambdaFunction(dataStack, "ContentActions", { runtime: Runtime.PYTHON_3_12, handler: "handler.handler", code: Code.fromInline("x") });
  const outputs: unknown[] = [];
  const extraStacks: Stack[] = [];
  const backend = {
    data: { resources: { cfnResources: { cfnTables, amplifyDynamoDbTables } } },
    homePageTrigger: { resources: { lambda: trigger } },
    addOutput: (value: unknown) => outputs.push(value),
    createStack: (name: string) => {
      const stack = new Stack(app, name, { env: environment });
      extraStacks.push(stack);
      return stack;
    },
  };
  return { backend, dataStack, extraStacks, contentActions, outputs, templates: () => [dataStack, ...extraStacks].map((stack) => Template.fromStack(stack)) };
}

function streamSpecificationsOf(template: Template): unknown[] {
  const tables = Object.values(template.findResources("AWS::DynamoDB::Table")).map((resource) => resource.Properties.StreamSpecification);
  const managed = Object.values(template.findResources("Custom::AmplifyDynamoDBTable")).map((resource) => resource.Properties.streamSpecification);
  return [...tables, ...managed].filter((specification) => specification !== undefined);
}

function wireFake(request: Parameters<typeof resolvePlugins>[0], resolveOptions: Parameters<typeof resolvePlugins>[1], projectionEnabled = true, fake = fakeBackend()) {
  const plugins = resolvePlugins(request, resolveOptions);
  const graphqlStack = fake.dataStack;
  const backend = {
    ...fake.backend,
    data: {
      resources: {
        ...fake.backend.data.resources,
        graphqlApi: { apiId: "api" },
        cfnResources: { ...fake.backend.data.resources.cfnResources, cfnGraphqlApi: { attrGraphQlUrl: "https://example.test/graphql" } },
      },
    },
  };
  assert.ok(graphqlStack);
  wirePlugins(backend, plugins, fake.contentActions, projectionEnabled);
  return { ...fake, plugins };
}

function resourceTypes(templates: Template[]): string[] {
  return templates.flatMap((template) => Object.values(template.toJSON().Resources as Record<string, { Type: string }>).map((resource) => resource.Type));
}

const behaviours: Record<string, () => Promise<unknown>> = {
  async the_defaults_are_justified_and_configurable() {
    assert.equal(DEFAULT_DEBOUNCE_SECONDS, 300, "the window equals the HTML s-maxage the writers set");
    assert.deepEqual(resolveHomePageConfig("home-page"), { debounceSeconds: 300, intervalHours: null, purge: false });
    assert.deepEqual(resolveHomePageConfig({ name: "home-page", debounceSeconds: 60, intervalHours: 6 }), { debounceSeconds: 60, intervalHours: 6, purge: false });
    const directory = siteDirectory({ homePage: { freshness: { debounceSeconds: 120, intervalHours: 12, purge: true } } });
    assert.deepEqual(resolveHomePageConfig("home-page", { staticDir: directory }), { debounceSeconds: 120, intervalHours: 12, purge: true }, "projection.json supplies the freshness");
    assert.deepEqual(resolveHomePageConfig({ name: "home-page", debounceSeconds: 30, intervalHours: null }, { staticDir: directory }), { debounceSeconds: 30, intervalHours: null, purge: true }, "the request wins over projection.json");
    assert.deepEqual(resolveHomePageConfig("home-page", { staticDir: siteDirectory({ homePage: {} }) }), { debounceSeconds: 300, intervalHours: null, purge: false });
    assert.throws(() => resolveHomePageConfig({ name: "home-page", debounceSeconds: 0 }), /whole number of seconds/);
    assert.throws(() => resolveHomePageConfig({ name: "home-page", debounceSeconds: 1.5 }), /whole number of seconds/);
    assert.throws(() => resolveHomePageConfig({ name: "home-page", intervalHours: 0 }), /hours/);
    assert.throws(() => resolveHomePageConfig({ name: "home-page", sleep: 1 }), /Unknown home-page plugin settings: sleep/);
    assert.throws(() => resolveHomePageConfig("home-page", { staticDir: siteDirectory({ homePage: { freshness: { purge: "yes" } } }) }), /purge must be true or false/);
    assert.throws(() => resolveHomePageConfig("home-page", { staticDir: siteDirectory({ homePage: { freshness: { windows: 1 } } }) }), /Unknown homePage.freshness settings: windows/);
    return {};
  },

  async purge_is_off_unless_the_site_turns_it_on() {
    assert.equal(resolveHomePageConfig("home-page").purge, false);
    assert.equal(resolveHomePageConfig("home-page", { staticDir: siteDirectory({ homePage: {} }) }).purge, false);
    assert.equal(homePagePlugin.publicSettings(resolveHomePageConfig("home-page")).purge, false);
    return {};
  },

  async a_site_with_the_plugin_but_no_home_page_setting_is_refused() {
    assert.throws(() => readProjectionFreshness({ staticDir: siteDirectory({ site: {} }) }), /needs a "homePage" setting/);
    assert.equal(readProjectionFreshness({ staticDir: siteDirectory(undefined) }), undefined);
    assert.equal(readProjectionFreshness({}), undefined);
    return {};
  },

  async a_site_that_does_not_ask_for_the_plugin_synthesizes_no_new_resource() {
    assert.deepEqual(resolvePlugins(undefined), []);
    assert.deepEqual(resolvePlugins([]), []);
    assert.deepEqual(resolvePlugins(["signup"]).map(({ plugin }) => plugin.manifest.name), ["signup"]);
    const untouchedBackend = new Proxy({}, { get: () => assert.fail("a site without plugins must not touch the backend") });
    wirePlugins(untouchedBackend, [], undefined as never);
    const withoutPlugin = fakeBackend();
    const untouched = withoutPlugin.templates().map((template) => JSON.stringify(template.toJSON()));
    wirePlugins({ ...withoutPlugin.backend, data: { resources: { ...withoutPlugin.backend.data.resources, graphqlApi: { apiId: "a" }, cfnResources: { ...withoutPlugin.backend.data.resources.cfnResources, cfnGraphqlApi: { attrGraphQlUrl: "u" } } } } }, [], withoutPlugin.contentActions);
    assert.deepEqual(withoutPlugin.templates().map((template) => JSON.stringify(template.toJSON())), untouched, "no stack changed");
    assert.equal(withoutPlugin.extraStacks.length, 0, "no stack was created");
    assert.equal(withoutPlugin.outputs.length, 0, "no output was added");
    const types = resourceTypes(withoutPlugin.templates());
    for (const type of ["AWS::Lambda::EventSourceMapping", "AWS::Events::Rule"]) assert.equal(types.includes(type), false, `no ${type}`);
    assert.deepEqual(streamSpecificationsOf(withoutPlugin.templates()[0]), [], "the Reference table is left as it was");
    return {};
  },

  async the_plugin_is_opt_in_by_name() {
    assert.equal(KNOWN_PLUGINS["home-page"], homePagePlugin);
    assert.deepEqual(homePageManifest, { name: "home-page", contract: 1, models: [], mutations: [], guest: { mutations: [] }, newsroomPanels: [], staticAssets: [] });
    assert.deepEqual(homePagePlugin.schemaDefinitions(), {});
    return {};
  },

  async the_plugin_adds_the_stream_the_trigger_the_scheduler_and_nothing_else() {
    const { templates, extraStacks, outputs, contentActions } = wireFake(["home-page"], { staticDir: siteDirectory({ homePage: {} }) });
    const [data, ...others] = templates();
    assert.deepEqual(streamSpecificationsOf(data), [{ streamViewType: "NEW_AND_OLD_IMAGES" }], "the table manager's table streams old and new images");
    assert.ok(JSON.stringify(others.map((template) => template.toJSON())).includes("TableStreamArn") || JSON.stringify(data.toJSON()).includes("TableStreamArn"), "the stream ARN is the managed table's TableStreamArn attribute");
    const mapping = others.flatMap((template) => Object.values(template.findResources("AWS::Lambda::EventSourceMapping")));
    assert.equal(mapping.length, 1);
    assert.deepEqual(
      { ...mapping[0].Properties, EventSourceArn: undefined, FunctionName: undefined, FilterCriteria: undefined },
      { BatchSize: 100, MaximumBatchingWindowInSeconds: 10, BisectBatchOnFunctionError: true, MaximumRetryAttempts: 2, StartingPosition: "TRIM_HORIZON", EventSourceArn: undefined, FunctionName: undefined, FilterCriteria: undefined },
    );
    assert.equal(mapping[0].Properties.FilterCriteria.Filters[0].Pattern, homePageStreamFilterPattern());
    const pattern = JSON.parse(homePageStreamFilterPattern());
    assert.deepEqual(pattern.$or[0], { eventName: ["REMOVE"] }, "a removal has no new image, so the filter lets it through");
    assert.equal(others.flatMap((template) => Object.keys(template.findResources("AWS::Events::Rule"))).length, 0, "no interval rule unless the site sets one");
    data.hasResourceProperties("AWS::IAM::Role", { AssumeRolePolicyDocument: Match.objectLike({ Statement: [Match.objectLike({ Principal: { Service: "scheduler.amazonaws.com" } })] }) });
    const policies = JSON.stringify(data.toJSON());
    assert.ok(policies.includes("scheduler:CreateSchedule") && policies.includes("schedule/default/papyrus-home-page-snapshot-*"));
    assert.ok(policies.includes("iam:PassRole") && policies.includes("papyrus-projection-locks"));
    assert.ok(policies.includes("dynamodb:PutItem") && policies.includes("dynamodb:DeleteItem"));
    assert.deepEqual(extraStacks.length, 1, "one extra stack: the stream mapping");
    assert.equal(outputs.length, 1, "only the plugins output");
    const environmentVariables = Object.values(data.findResources("AWS::Lambda::Function")).map((resource) => resource.Properties.Environment?.Variables ?? {});
    const triggerEnvironment = environmentVariables.find((variables) => "PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS" in variables);
    assert.equal(triggerEnvironment?.PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS, "300");
    assert.equal(triggerEnvironment?.PAPYRUS_PROJECTION_LOCK_TABLE, "papyrus-projection-locks");
    assert.ok("PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN" in (triggerEnvironment ?? {}) && "PAPYRUS_HOME_PAGE_SCHEDULER_ROLE_ARN" in (triggerEnvironment ?? {}));
    assert.ok(contentActions);
    const published = (outputs[0] as { custom: Record<string, Record<string, unknown>> }).custom[PLUGINS_OUTPUT_KEY];
    assert.deepEqual(published, { "home-page": { contract: 1, debounceSeconds: 300, intervalHours: null, purge: false } });
    return {};
  },

  async plain_cloudformation_tables_are_found_by_name_too() {
    for (const mode of ["cfn", "cfn-generated-name"] as const) {
      const { templates } = wireFake(["home-page"], {}, true, fakeBackend(mode));
      assert.deepEqual(streamSpecificationsOf(templates()[0]), [{ StreamViewType: "NEW_AND_OLD_IMAGES" }]);
    }
    return {};
  },

  async an_interval_adds_one_rule_that_runs_the_snapshot_task() {
    const { templates } = wireFake([{ name: "home-page", intervalHours: 6, debounceSeconds: 90 }], {});
    const rules = templates().flatMap((template) => Object.values(template.findResources("AWS::Events::Rule")));
    assert.equal(rules.length, 1);
    assert.equal(rules[0].Properties.ScheduleExpression, "rate(6 hours)");
    assert.deepEqual(rules[0].Properties.Targets[0].RetryPolicy, { MaximumRetryAttempts: 0 });
    assert.equal(rules[0].Properties.Targets[0].Input, JSON.stringify(HOME_PAGE_SNAPSHOT_TASK));
    const fractional = wireFake([{ name: "home-page", intervalHours: 1.5 }], {});
    assert.equal(fractional.templates().flatMap((template) => Object.values(template.findResources("AWS::Events::Rule")))[0].Properties.ScheduleExpression, "rate(90 minutes)");
    const environmentVariables = Object.values(templates()[0].findResources("AWS::Lambda::Function")).map((resource) => resource.Properties.Environment?.Variables ?? {});
    assert.ok(environmentVariables.some((variables) => variables.PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS === "90"));
    return {};
  },

  async the_plugin_needs_a_publication() {
    assert.throws(() => wireFake(["home-page"], {}, false), /S3 projection/);
    return {};
  },
};

async function main() {
  const requested = process.argv[2];
  if (requested !== undefined) {
    const behaviour = behaviours[requested];
    assert.ok(behaviour, `unknown behaviour ${requested}`);
    await behaviour();
    console.log(JSON.stringify({ ok: true }));
    return;
  }
  for (const [name, behaviour] of Object.entries(behaviours)) {
    await behaviour();
    console.log(`ok ${name}`);
  }
  console.log("home-page plugin ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
