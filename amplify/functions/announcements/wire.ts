import { Stack } from "aws-cdk-lib";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { ANNOUNCEMENTS_TIMEOUT_SECONDS } from "./resource";

/** X's endpoints (docs.x.com, 2026-11-12). The function reads them from its environment; tests point them at a fake server. */
export const X_ENDPOINTS = {
  X_AUTHORIZE_URL: "https://x.com/i/oauth2/authorize",
  X_TOKEN_URL: "https://api.x.com/2/oauth2/token",
  X_REVOKE_URL: "https://api.x.com/2/oauth2/revoke",
  X_API_BASE: "https://api.x.com",
};

/** Everything under this prefix is the function's: the client secret, and each account's refresh and access tokens. Nothing else. */
export const announcementsParameterPrefix = (siteId: string) => `/papyrus/${siteId}/announcements/x`;

/**
 * Environment and least-privilege IAM for the announcements function: read and write on its two model tables, and
 * SecureString parameters under the site's announcements path. The tables are written directly with the function's role,
 * so the console reads them only through the function.
 */
export function wireAnnouncements(backend: any, siteId: string): void {
  const lambda = backend.announcements.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  const tables = backend.data.resources.tables as Record<string, ITable>;
  const settings = tables.AnnouncementSettings;
  const connection = tables.XConnection;
  settings.grantReadWriteData(lambda);
  connection.grantReadWriteData(lambda);
  lambda.addEnvironment("SITE_ID", siteId);
  lambda.addEnvironment("ANNOUNCEMENT_SETTINGS_TABLE", settings.tableName);
  lambda.addEnvironment("X_CONNECTION_TABLE", connection.tableName);
  lambda.addEnvironment("X_REFRESH_LEASE_SECONDS", String(ANNOUNCEMENTS_TIMEOUT_SECONDS));
  for (const [name, value] of Object.entries(X_ENDPOINTS)) lambda.addEnvironment(name, value);
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"],
      resources: [`arn:aws:ssm:${stack.region}:${stack.account}:parameter${announcementsParameterPrefix(siteId)}/*`],
    }),
  );
}
