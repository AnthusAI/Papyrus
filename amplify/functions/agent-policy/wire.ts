import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { ADMIN_AGENT_POLICY_KEY_PATTERN } from "../../agents/admin-policy-grant";

/**
 * Environment and least-privilege IAM for the agent-policy function: read and write on the two site document tables, get and put on the agent policy objects of the
 * media bucket (no delete, so every version stays), and the person-only app clients it checks the token against.
 */
export function wireAgentPolicy(backend: any, bucketName: string, bucketArn: string, personOnlyClientIds: string[], tenantId: string): void {
  const lambda = backend.agentPolicy.resources.lambda as LambdaFunction;
  const tables = backend.data.resources.tables as Record<string, ITable>;
  for (const table of [tables.SiteDocument, tables.SiteDocumentVersion]) table.grantReadWriteData(lambda);
  lambda.addToRolePolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: ["dynamodb:DescribeTable"], resources: [tables.SiteDocumentVersion.tableArn] }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: ["s3:GetObject", "s3:PutObject"], resources: [`${bucketArn}/${ADMIN_AGENT_POLICY_KEY_PATTERN}`] }),
  );
  lambda.addEnvironment("MEDIA_BUCKET", bucketName);
  lambda.addEnvironment("SITE_DOCUMENT_TABLE", tables.SiteDocument.tableName);
  lambda.addEnvironment("SITE_DOCUMENT_VERSION_TABLE", tables.SiteDocumentVersion.tableName);
  lambda.addEnvironment("PERSON_ONLY_CLIENT_IDS", personOnlyClientIds.join(","));
  lambda.addEnvironment("PAPYRUS_TENANT_ID", tenantId);
}
