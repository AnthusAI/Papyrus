import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { a, defineBackend, defineFunction } from "@aws-amplify/backend";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { NestedStack, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { Role, ServicePrincipal, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Bucket } from "aws-cdk-lib/aws-s3";
import type { S3Client } from "@aws-sdk/client-s3";
import { schema, schemaWithPlugins } from "../amplify/data/schema";
import { assignmentAction } from "../amplify/functions/assignment-action/resource";
import { ASSIGNMENT_DATA_FIELDS, scopeAssignmentDataAccess } from "../amplify/functions/assignment-action/data-access";

for (const [name, definition] of [
  ["base", schema],
  ["with plugin definitions", schemaWithPlugins({})],
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
    const storage = new NestedStack(stack.nestedStackParent ?? stack, "AssignmentSharedStorage");
    new Bucket(storage, "Media").grantReadWrite(lambda);
    const apiArn = "arn:aws:appsync:us-east-1:123456789012:apis/synthetic";
    scopeAssignmentDataAccess(lambda, apiArn);
    const otherRole = new Role(stack, "UnrelatedWorkerRole", { assumedBy: new ServicePrincipal("lambda.amazonaws.com") });
    otherRole.addToPolicy(new PolicyStatement({ actions: ["appsync:GraphQL"], resources: [`${apiArn}/types/Query/*`] }));
    const template = Template.fromStack(stack).toJSON();
    const assertLocalReferences = (value: unknown): void => {
      if (Array.isArray(value)) return value.forEach(assertLocalReferences);
      if (!value || typeof value !== "object") return;
      const object = value as Record<string, unknown>;
      const attribute = object["Fn::GetAtt"];
      if (attribute) {
        const target = Array.isArray(attribute) ? attribute[0] : String(attribute).split(".")[0];
        assert.ok(template.Resources[String(target)], `cross-stack reference must remain valid: ${target}`);
      }
      Object.values(object).forEach(assertLocalReferences);
    };
    assertLocalReferences(template.Resources);
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
    assert.ok(!graphqlResources.includes("/types/Query/*") && !graphqlResources.includes("/types/Mutation/*"),
      "assignment permissions must name fields rather than whole API operation types");
    assert.ok(!graphqlResources.includes("Subscription"));
    assert.deepEqual(graphql[0].Resource, ASSIGNMENT_DATA_FIELDS.map((field) => `${apiArn}/types/${field}`));
    const allowed = new Set(graphql[0].Resource);
    for (const field of ["Query/fields/getAssignment", "Mutation/fields/updateAssignment",
      "Mutation/fields/createAssignmentEvent", "Query/fields/listKnowledgeCorporaByRoleAndName",
      "Query/fields/itemBySlug", "Query/fields/getNewsroomSection", "Mutation/fields/createReference",
      "Mutation/fields/updateReference", "Mutation/fields/createKnowledgeImportRun",
      "Mutation/fields/createModelAttachmentUpload", "Mutation/fields/completeModelAttachmentUpload",
      "Mutation/fields/updateNewsroomSummary"]) {
      assert.ok(allowed.has(`${apiArn}/types/${field}`), `required operation: ${field}`);
    }
    for (const field of ["Mutation/fields/manageUserRole", "Mutation/fields/createUserRoleAssignment",
      "Mutation/fields/publishItem", "Mutation/fields/unpublishItem", "Mutation/fields/deleteItem",
      "Mutation/fields/updateItem", "Mutation/fields/deleteReference", "Mutation/fields/deleteAssignment",
      "Mutation/fields/createEditorialPolicy", "Mutation/fields/updateEditorialPolicy",
      "Query/fields/listUserProfiles", "Subscription/fields/onCreateAssignment"]) {
      assert.ok(!allowed.has(`${apiArn}/types/${field}`), `unrelated operation must have no grant: ${field}`);
    }
    assert.ok(![...allowed].some((resource) => String(resource).includes("*")));
    const otherPolicies = resources.filter((resource) => resource.Type === "AWS::IAM::Policy"
      && (resource.Properties.Roles ?? []).some((candidate: unknown) => JSON.stringify(candidate) === JSON.stringify(stack.resolve(otherRole.roleName))));
    assert.ok(JSON.stringify(otherPolicies).includes("/types/Query/*"), "another function's policy must remain unchanged");
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
