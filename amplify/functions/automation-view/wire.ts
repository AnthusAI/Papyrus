import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import {
  MONITORING_TABLE_PARAMETER,
  MONITORING_VIEW_TABLE_ACTIONS,
  monitoringViewParameterArn,
  monitoringViewTableArns,
} from "../monitoring-view/wire";

/** The two reads the function makes of its own site's API with its own role. It writes nothing. */
export const AUTOMATION_VIEW_FUNCTION_FIELDS = ["Query/fields/listAutomations", "Query/fields/getProcedureRun"];

/**
 * Environment and least-privilege IAM for the automation-view function: two fields of the site's own API,
 * and the same read-only grant on the monitoring table that the Monitoring page has. A site outside the
 * monitoring account finds no parameter and the page lists its records without runs.
 */
export function wireAutomationView(backend: any): void {
  const lambda = backend.automationView.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  lambda.addEnvironment("PAPYRUS_MONITORING_TABLE_PARAMETER", MONITORING_TABLE_PARAMETER);
  const apiId = backend.data.resources.graphqlApi.apiId as string;
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: AUTOMATION_VIEW_FUNCTION_FIELDS.map((field) => `arn:aws:appsync:${stack.region}:${stack.account}:apis/${apiId}/types/${field}`),
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter"],
      resources: [monitoringViewParameterArn(stack.region, stack.account)],
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: MONITORING_VIEW_TABLE_ACTIONS,
      resources: monitoringViewTableArns(stack.region, stack.account),
    }),
  );
}
