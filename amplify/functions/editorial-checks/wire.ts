import { secret } from "@aws-amplify/backend";
import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

/** The model operations the function performs with its own role. The two context reads are its least-privilege access to private policy. */
export const EDITORIAL_CHECKS_FUNCTION_FIELDS = [
  "Query/fields/listKnowledgeCorporaByRoleAndName",
  "Query/fields/getEditorialContext",
  "Query/fields/listEditorialPolicies",
  "Query/fields/getEditorialCheckSettings",
  "Query/fields/listEditorialFeedbacks",
  "Mutation/fields/createEditorialPolicy",
  "Mutation/fields/updateEditorialPolicy",
  "Query/fields/getItem",
  "Query/fields/getEditorialCheckRun",
  "Mutation/fields/createEditorialCheckRun",
  "Mutation/fields/updateEditorialCheckRun",
];

export const EDITORIAL_CHECKS_SECRETS = ["TYPESAFE_API_KEY", "OPENAI_API_KEY"];

/**
 * SSM parameters holding the provider keys. A Python function reads its secret()
 * values itself (Amplify only resolves them for Node functions), so it needs read
 * access to the app's branch and shared secret paths, and to the sandbox paths.
 */
export function editorialChecksSecretParameters(region: string, account: string, appId: string): string[] {
  const arn = (path: string) => `arn:aws:ssm:${region}:${account}:parameter/amplify/${path}`;
  return EDITORIAL_CHECKS_SECRETS.flatMap((name) => [
    arn(`papyrus/*/${name}`),
    arn(`shared/papyrus/${name}`),
    ...(appId ? [arn(`${appId}/*/${name}`), arn(`shared/${appId}/${name}`)] : []),
  ]);
}

/**
 * Environment, secrets and least-privilege IAM for the editorial-checks function. Every site gets
 * these; whether checks run is a stored setting (EditorialCheckSettings.enabled), not a deploy flag.
 */
export function wireEditorialChecks(backend: any): void {
  const lambda = backend.editorialChecks.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  for (const name of EDITORIAL_CHECKS_SECRETS) backend.editorialChecks.addEnvironment(name, secret(name));
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter", "ssm:GetParameters"],
      resources: editorialChecksSecretParameters(stack.region, stack.account, (process.env.AWS_APP_ID ?? "").trim()),
    }),
  );
  const apiId = backend.data.resources.graphqlApi.apiId as string;
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: EDITORIAL_CHECKS_FUNCTION_FIELDS.map((field) => `arn:aws:appsync:${stack.region}:${stack.account}:apis/${apiId}/types/${field}`),
    }),
  );
}
