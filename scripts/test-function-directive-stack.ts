/**
 * CloudFormation refuses a stack with more than 500 resources. Every Lambda-backed field of the data API lands in
 * Amplify's `FunctionDirectiveStack`, and an unshared field costs six resources there (data source, role, policy, two
 * function configurations, resolver), so adding fields without sharing the Lambda data source broke the deploy of
 * Papyrus 5.33.0 ("[TooManyResourcesInStack] ... FunctionDirectiveStack: 505"). This synthesizes the real backend with
 * every plugin enabled and holds that stack well under the limit.
 */
process.env.AWS_BRANCH = "main";
process.env.AWS_APP_ID = "dtestapp0001";
process.env.CDK_CONTEXT_JSON = JSON.stringify({
  "aws:cdk:bundling-stacks": [],
  "amplify-backend-namespace": "dtestapp0001",
  "amplify-backend-name": "main",
  "amplify-backend-type": "branch",
});

import assert from "node:assert/strict";

const FUNCTION_DIRECTIVE_STACK_BUDGET = 450;
const CLOUDFORMATION_STACK_LIMIT = 500;

const computeRoleArn = "arn:aws:iam::123456789012:role/AmplifyComputeRole-abc";
const plugins = [
  {
    name: "newsletter",
    siteId: "example",
    siteOrigin: "https://news.example.com",
    computeRoleArn,
    sendingDomain: "example.com",
    fromAddress: "newsletter@example.com",
    fromName: "Example News",
    theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" },
    lists: [
      { id: "alerts-x", name: "Alerts", description: "Breaking items.", kind: "alert", rule: { sections: ["Security"], tags: ["breaking"] } },
    ],
  },
  { name: "reader-steering", computeRoleArn },
  { name: "signup", forms: ["news"] },
];

async function main() {
  const { NestedStack } = await import("aws-cdk-lib");
  const { Template } = await import("aws-cdk-lib/assertions");
  const { defineSiteBackend } = await import("../amplify/site-backend");

  const backend = defineSiteBackend({
    defaultBrand: "p-apyr-us",
    backend: { productionAppId: "dbsyytcm9drqa", plugins: plugins },
  } as never);
  const app = (backend as any).data.resources.graphqlApi.node.root;

  const nested: any[] = [];
  const walk = (construct: any) => {
    for (const child of construct.node.children) {
      if (child instanceof NestedStack) nested.push(child);
      walk(child);
    }
  };
  walk(app);
  const stack = nested.find((candidate) => candidate.node.path.endsWith("/FunctionDirectiveStack"));
  assert.ok(stack, "the data API has a FunctionDirectiveStack");

  const resources = Object.values(Template.fromStack(stack).toJSON().Resources ?? {}) as { Type: string }[];
  const count = (type: string) => resources.filter((resource) => resource.Type === type).length;
  const resolvers = count("AWS::AppSync::Resolver");
  const dataSources = count("AWS::AppSync::DataSource");

  assert.ok(resolvers > 60, `expected the Lambda-backed resolvers in the stack, found ${resolvers}`);
  assert.ok(
    resources.length < FUNCTION_DIRECTIVE_STACK_BUDGET,
    `FunctionDirectiveStack has ${resources.length} resources; keep it under ${FUNCTION_DIRECTIVE_STACK_BUDGET} (CloudFormation fails at ${CLOUDFORMATION_STACK_LIMIT}). Handle new fields with functionHandler() from amplify/data/function-handler.ts so they share a Lambda data source.`,
  );
  assert.ok(
    dataSources < resolvers / 2,
    `${dataSources} data sources for ${resolvers} resolvers: Lambda fields must share one data source per function`,
  );
  console.log(`FunctionDirectiveStack: ${resources.length} resources, ${resolvers} resolvers, ${dataSources} data sources`);
}

main().then(
  () => console.log("function directive stack tests passed"),
  (error) => {
    console.error(error);
    process.exit(1);
  },
);
