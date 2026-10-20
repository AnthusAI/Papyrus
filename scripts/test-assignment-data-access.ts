import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { a, defineBackend, defineFunction } from "@aws-amplify/backend";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import type { S3Client } from "@aws-sdk/client-s3";
import { schema, schemaWithPlugins } from "../amplify/data/schema";
import { assignmentAction } from "../amplify/functions/assignment-action/resource";
import { editorialChecksSchemaDefinitions } from "../amplify/plugins/editorial-checks/schema";

for (const [name, definition] of [
  ["base", schema],
  ["editorial-checks", schemaWithPlugins(editorialChecksSchemaDefinitions())],
] as const) {
  const registrations = definition.transform().functionSchemaAccess.filter(
    (access) => access.resourceProvider === assignmentAction,
  );
  assert.equal(registrations.length, 1, `${name}: assignment data client needs generated configuration`);
  assert.deepEqual(registrations[0].actions, ["query", "mutate"], `${name}: no subscription access is needed`);
}

async function verifyGeneratedConfiguration() {
  const directory = mkdtempSync(join(resolve("."), ".assignment-data-access-"));
  const previousContext = process.env.CDK_CONTEXT_JSON;
  try {
    process.env.CDK_CONTEXT_JSON = JSON.stringify({
      "amplify-backend-name": "synthetic",
      "amplify-backend-namespace": "offline-test",
      "amplify-backend-type": "standalone",
    });
    const entry = join(directory, "handler.ts");
    writeFileSync(entry, "export const handler = async () => ({ ok: true });\n");
    const worker = defineFunction({ name: "synthetic-assignment", entry, resourceGroupName: "data" });
    const definition = a.schema({
      Entry: a.model({ value: a.string() }).authorization((allow) => [allow.publicApiKey()]),
    }).authorization((allow) => [allow.resource(worker).to(["query", "mutate"])]);
    const require = createRequire(resolve("package.json"));
    // DataFactory exposes its import-stack argument specifically for SDK tests.
    const factoryPath = join(dirname(require.resolve("@aws-amplify/backend-data")), "factory.js");
    const { DataFactory } = await import(pathToFileURL(factoryPath).href);
    const backend = defineBackend({
      worker,
      data: new DataFactory({ name: "PapyrusCmsApi", schema: definition,
        authorizationModes: { defaultAuthorizationMode: "apiKey" } }, ""),
    });
    const lambda = backend.worker.resources.lambda;
    const stack = Stack.of(lambda);
    const template = Template.fromStack(stack).toJSON();
    const role = stack.resolve(lambda.role!.roleName);
    const resources = Object.values(template.Resources) as Array<{
      Type: string; Properties: Record<string, any>;
    }>;
    const functionResource = resources.find((resource) => resource.Type === "AWS::Lambda::Function"
      && resource.Properties.Environment?.Variables?.AMPLIFY_SSM_ENV_CONFIG);
    assert.ok(functionResource);
    const entries = JSON.parse(functionResource.Properties.Environment.Variables.AMPLIFY_SSM_ENV_CONFIG);
    const names = Object.keys(entries).sort();
    assert.deepEqual(names, ["AMPLIFY_DATA_DEFAULT_NAME", "AMPLIFY_DATA_PAPYRUS_CMS_API_GRAPHQL_ENDPOINT",
      "AMPLIFY_DATA_PAPYRUS_CMS_API_MODEL_INTROSPECTION_SCHEMA_BUCKET_NAME",
      "AMPLIFY_DATA_PAPYRUS_CMS_API_MODEL_INTROSPECTION_SCHEMA_KEY", "PAPYRUS_CMS_API_GRAPHQL_ENDPOINT"]);
    const rolePolicies = resources.filter((resource) => resource.Type === "AWS::IAM::Policy"
      && (resource.Properties.Roles ?? []).some((candidate: unknown) => JSON.stringify(candidate) === JSON.stringify(role)));
    const statements = rolePolicies.flatMap((resource) => resource.Properties.PolicyDocument.Statement);
    const graphql = statements.filter((statement) => statement.Action === "appsync:GraphQL");
    assert.equal(graphql.length, 1);
    const graphqlResources = JSON.stringify(graphql[0].Resource);
    assert.ok(graphqlResources.includes("/types/Query/*") && graphqlResources.includes("/types/Mutation/*"));
    assert.ok(!graphqlResources.includes("Subscription"));
    const schemaReads = statements.filter((statement) => statement.Action === "s3:GetObject");
    assert.equal(schemaReads.length, 1);
    assert.ok(JSON.stringify(schemaReads[0].Resource).includes("/modelIntrospectionSchema.json"));
    const parameterReads = statements.filter((statement) => statement.Action === "ssm:GetParameters");
    assert.equal(parameterReads.length, 1);
    assert.equal(parameterReads[0].Resource.length, 5);
    assert.ok(!JSON.stringify(parameterReads).includes("parameter/*"));
    const environment = Object.fromEntries(names.map((name) => [name,
      name === "AMPLIFY_DATA_DEFAULT_NAME" ? "AMPLIFY_DATA_PAPYRUS_CMS_API"
        : name.endsWith("BUCKET_NAME") ? "synthetic-schema-bucket"
          : name.endsWith("SCHEMA_KEY") ? "modelIntrospectionSchema.json" : "https://example.invalid/graphql"]));
    const requests: unknown[] = [];
    const s3 = { send: async (command: { input: unknown }) => {
      requests.push(command.input);
      return { Body: { transformToString: async () => '{"models":{}}' } };
    } } as unknown as S3Client;
    const config = await getAmplifyDataClientConfig(environment as never, s3);
    assert.equal(config.resourceConfig.API.GraphQL.endpoint, "https://example.invalid/graphql");
    assert.equal(config.resourceConfig.API.GraphQL.defaultAuthMode, "iam");
    assert.deepEqual(requests, [{ Bucket: "synthetic-schema-bucket", Key: "modelIntrospectionSchema.json" }]);
    await assert.rejects(getAmplifyDataClientConfig({} as never, s3), /malformed/);
    assert.equal(requests.length, 1, "missing configuration must fail before storage or API access");
    console.log("Assignment registration, synthesized access/configuration and offline client initialization pass.");
  } finally {
    if (previousContext === undefined) delete process.env.CDK_CONTEXT_JSON;
    else process.env.CDK_CONTEXT_JSON = previousContext;
    rmSync(directory, { recursive: true, force: true });
  }
}

verifyGeneratedConfiguration().catch((error) => { console.error(error); process.exitCode = 1; });
