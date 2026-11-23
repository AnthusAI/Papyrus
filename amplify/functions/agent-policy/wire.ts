import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { Stack } from "aws-cdk-lib";
import { ADMIN_AGENT_POLICY_KEY_PATTERN } from "../../agents/admin-policy-grant";
import { allowWakeSending } from "../../agents/wake-queue";
import { connectToSiteApi } from "../../site-api-access";

/** The listener index (`tenants/<tenant>/site/listeners/<version>.json`): which agents listen for changes, so a resume knows whose stopped wakes to send again. Read only. */
export const LISTENER_INDEX_KEY_PATTERN = "tenants/*/site/listeners/*";

/** A resume reads one agent's runs, with the wake each kept, through the run index by automation (agent_poke_in.py). Nothing else of the site's API. */
export const AGENT_POLICY_FUNCTION_FIELDS = ["Query/fields/listProcedureRunsByAutomationAndRequestedAt"];

/**
 * Environment and least-privilege IAM for the agent-policy function: read and write on the two site document tables and query on their indexes, get and put on the agent policy objects of the
 * media bucket (no delete, so every version stays), and the person-only app clients it checks the token against. A resume also sends again the wakes the pause stopped
 * (agent_poke_in.py), so the function reads the listener index, reads one agent's runs through the run index by automation with its own role, and puts wakes on
 * the site's own wake queue.
 * A first (bootstrap) deploy leaves the tenancy models out, so with no site document tables there is nothing to wire and the function is not yet callable.
 */
export function wireAgentPolicy(backend: any, bucketName: string, bucketArn: string, personOnlyClientIds: string[], brandId: string): void {
  const lambda = backend.agentPolicy.resources.lambda as LambdaFunction;
  const tables = backend.data.resources.tables as Record<string, ITable>;
  if (tables.SiteDocument === undefined || tables.SiteDocumentVersion === undefined) return;
  for (const table of [tables.SiteDocument, tables.SiteDocumentVersion]) table.grantReadWriteData(lambda);
  lambda.addToRolePolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: ["dynamodb:DescribeTable"], resources: [tables.SiteDocumentVersion.tableArn] }),
  );
  // The catalogue reads a document's versions through the tables' indexes (siteDocumentVersionsByDocumentIdAndVersion), which a table grant does not cover.
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["dynamodb:Query"],
      resources: [tables.SiteDocument, tables.SiteDocumentVersion].map((table) => `${table.tableArn}/index/*`),
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: ["s3:GetObject", "s3:PutObject"], resources: [`${bucketArn}/${ADMIN_AGENT_POLICY_KEY_PATTERN}`] }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: ["s3:GetObject"], resources: [`${bucketArn}/${LISTENER_INDEX_KEY_PATTERN}`] }),
  );
  const stack = Stack.of(lambda);
  const apiId = backend.data.resources.graphqlApi.apiId as string;
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: AGENT_POLICY_FUNCTION_FIELDS.map((field) => `arn:aws:appsync:${stack.region}:${stack.account}:apis/${apiId}/types/${field}`),
    }),
  );
  connectToSiteApi(lambda, backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  allowWakeSending(lambda, brandId);
  lambda.addEnvironment("MEDIA_BUCKET", bucketName);
  lambda.addEnvironment("SITE_DOCUMENT_TABLE", tables.SiteDocument.tableName);
  lambda.addEnvironment("SITE_DOCUMENT_VERSION_TABLE", tables.SiteDocumentVersion.tableName);
  lambda.addEnvironment("PERSON_ONLY_CLIENT_IDS", personOnlyClientIds.join(","));
}
