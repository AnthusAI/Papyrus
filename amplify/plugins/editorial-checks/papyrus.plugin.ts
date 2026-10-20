import { secret } from "@aws-amplify/backend";
import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { PapyrusPlugin, PluginManifest, PluginRequest, PluginWiringContext } from "../types";
import { editorialChecks } from "./function/resource";
import { editorialChecksSchemaDefinitions } from "./schema";

/** Runtime settings (lanes, models, deadline) live in EditorialCheckSettings, edited in the newsroom; enabling the plugin takes no options. */
export type EditorialChecksPluginConfig = Record<string, never>;

export const EDITORIAL_CHECKS_QUERIES = ["checkEditorial", "suggestEditorialRewrite", "draftEditorialQuestions", "tryEditorialPolicy"];
export const EDITORIAL_CHECKS_MUTATIONS = ["importEditorialStarterPack", "recalibrateEditorialPolicies"];

/** The model operations the function performs with its own role. */
export const EDITORIAL_CHECKS_FUNCTION_FIELDS = [
  "Query/fields/listEditorialPolicies",
  "Query/fields/getEditorialCheckSettings",
  "Query/fields/listEditorialFeedbacks",
  "Mutation/fields/createEditorialPolicy",
  "Mutation/fields/updateEditorialPolicy",
];

export const editorialChecksManifest: PluginManifest = {
  name: "editorial-checks",
  contract: 1,
  models: ["EditorialPolicy", "EditorialCheckSettings", "EditorialFeedback"],
  mutations: [...EDITORIAL_CHECKS_QUERIES, ...EDITORIAL_CHECKS_MUTATIONS],
  guest: { mutations: [] },
  newsroomPanels: [{ id: "editorial-checks", label: "Editorial checks" }],
  staticAssets: [],
};

export function resolveEditorialChecksConfig(request: PluginRequest): EditorialChecksPluginConfig {
  const raw = typeof request === "string" ? { name: request } : request;
  const unknown = Object.keys(raw).filter((key) => key !== "name");
  if (unknown.length > 0) throw new Error(`Unknown editorial-checks plugin settings: ${unknown.join(", ")} (runtime settings are edited in the newsroom)`);
  return {};
}

export const editorialChecksPlugin: PapyrusPlugin<EditorialChecksPluginConfig, { editorialChecks: typeof editorialChecks }> = {
  manifest: editorialChecksManifest,
  resolveConfig: resolveEditorialChecksConfig,
  functions: () => ({ editorialChecks }),
  schemaDefinitions: editorialChecksSchemaDefinitions,
  publicSettings: () => ({ contract: editorialChecksManifest.contract }),
  wire(backend, _config, context: PluginWiringContext) {
    const lambda = backend.editorialChecks.resources.lambda as LambdaFunction;
    const stack = Stack.of(lambda);
    lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", context.graphqlEndpoint);
    backend.editorialChecks.addEnvironment("TYPESAFE_API_KEY", secret("TYPESAFE_API_KEY"));
    backend.editorialChecks.addEnvironment("OPENAI_API_KEY", secret("OPENAI_API_KEY"));
    lambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["appsync:GraphQL"],
        resources: EDITORIAL_CHECKS_FUNCTION_FIELDS.map(
          (field) => `arn:aws:appsync:${stack.region}:${stack.account}:apis/${context.graphqlApiId}/types/${field}`,
        ),
      }),
    );
  },
};
