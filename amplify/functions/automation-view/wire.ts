import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import {
  MONITORING_TABLE_PARAMETER,
  MONITORING_VIEW_TABLE_ACTIONS,
  monitoringViewParameterArn,
  monitoringViewTableArns,
} from "../monitoring-view/wire";
import { connectToSiteApi } from "../../site-api-access";
import { allowWakeSending } from "../../agents/wake-queue";

/** The reads the function makes of its own site's API with its own role. It writes nothing there. Today reads the day's runs through the status index and the agents through the tenant index. */
export const AUTOMATION_VIEW_FUNCTION_FIELDS = [
  "Query/fields/getAutomation",
  "Query/fields/getNewsroomProcedureDefinition",
  "Query/fields/getProcedureRun",
  "Query/fields/listAutomations",
  "Query/fields/listAutomationsByTenant",
  "Query/fields/listProcedureRunsByProcedureAndRequestedAt",
  "Query/fields/listProcedureRunsByStatusAndRequestedAt",
];

/** Run now writes one row of its own to the monitoring table, in a monitor's partition (`MONITOR#<id>`), and nothing else. */
export const AUTOMATION_RUN_NOW_TABLE_ACTIONS = ["dynamodb:PutItem"];
export const AUTOMATION_RUN_NOW_LEADING_KEYS = ["MONITOR#*"];

/**
 * Environment and least-privilege IAM for the automation-view function: a few read fields of the site's own API,
 * the same read-only grant on the monitoring table that the Monitoring page has, one PutItem for Run now's row,
 * and permission to put a wake on the site's own wake queue (Run now). A site outside the
 * monitoring account finds no parameter and the page lists its records without runs.
 */
export function wireAutomationView(backend: any, brandId: string): void {
  const lambda = backend.automationView.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  connectToSiteApi(lambda, backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
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
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: AUTOMATION_RUN_NOW_TABLE_ACTIONS,
      resources: monitoringViewTableArns(stack.region, stack.account).slice(0, 1),
      conditions: { "ForAllValues:StringLike": { "dynamodb:LeadingKeys": AUTOMATION_RUN_NOW_LEADING_KEYS } },
    }),
  );
  allowWakeSending(lambda, brandId);
}
