import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { ADMIN_AGENT_POLICY_KEY_PATTERN } from "../../agents/admin-policy-grant";

/**
 * Environment and least-privilege IAM for the agent-policy function: read and write on the two site document tables and query on their indexes, get and put on the agent policy objects of the
 * media bucket (no delete, so every version stays), and the person-only app clients it checks the token against.
 * A first (bootstrap) deploy leaves the tenancy models out, so with no site document tables there is nothing to wire and the function is not yet callable.
 */
export function wireAgentPolicy(backend: any, bucketName: string, bucketArn: string, personOnlyClientIds: string[]): void {
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
  lambda.addEnvironment("MEDIA_BUCKET", bucketName);
  lambda.addEnvironment("SITE_DOCUMENT_TABLE", tables.SiteDocument.tableName);
  lambda.addEnvironment("SITE_DOCUMENT_VERSION_TABLE", tables.SiteDocumentVersion.tableName);
  lambda.addEnvironment("PERSON_ONLY_CLIENT_IDS", personOnlyClientIds.join(","));
}
