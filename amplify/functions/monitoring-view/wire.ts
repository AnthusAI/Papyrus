import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

/** The monitoring stack writes the table's name here (infra/monitoring/papyrus-monitoring.yaml). */
export const MONITORING_TABLE_PARAMETER = "/papyrus/monitoring/table-name";

/** Reads only: a single item or a key-range query. No Scan, no writes, no other table. */
export const MONITORING_VIEW_TABLE_ACTIONS = ["dynamodb:GetItem", "dynamodb:Query"];

/**
 * The monitoring table is auto-named by CloudFormation (`papyrus-monitoring-MonitoringTable-<id>`), so
 * the grant is the stack's table name prefix, not a wildcard on the account.
 */
export function monitoringViewTableArns(region: string, account: string): string[] {
  const table = `arn:aws:dynamodb:${region}:${account}:table/papyrus-monitoring-MonitoringTable-*`;
  return [table, `${table}/index/routing`];
}

export function monitoringViewParameterArn(region: string, account: string): string {
  return `arn:aws:ssm:${region}:${account}:parameter${MONITORING_TABLE_PARAMETER}`;
}

/**
 * Environment and least-privilege IAM for the monitoring-view function. A site outside the monitoring
 * account simply finds no parameter and the page says monitoring is not configured.
 */
export function wireMonitoringView(backend: any): void {
  const lambda = backend.monitoringView.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  lambda.addEnvironment("PAPYRUS_MONITORING_TABLE_PARAMETER", MONITORING_TABLE_PARAMETER);
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
