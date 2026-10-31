import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { buildMessageActionsSchemaDefinitions, PROSPECTUS_DATA_SOURCE_NAME } from "./message-actions";
import { buildProfileActionsSchemaDefinitions } from "./profile-actions";

/**
 * Fail-closed Prospectus authorization, behind `features.prospectusAuthorize` (default off). With the flag off nothing here
 * runs: the schema, the data sources, the function environments and the roles are exactly what they were before.
 *
 * With it on, three things change. Account-scoped mutations get a Prospectus pipeline function in front of them, the data
 * API gets an IAM-signed HTTP data source for it, and the Lambda resolvers that call `requireAuthorized` get the endpoint,
 * the switch and the permission to invoke the authorize route. The caller's account arrives in `X-Prospectus-Account`.
 */

const PROSPECTUS_STAGE_PATH = "/api/";
const EXECUTE_API_HOST = /^([a-z0-9]+)\.execute-api\.([a-z0-9-]+)\.amazonaws\.com$/;

export type ProspectusAuthorizePlan = {
  endpoint: string;
  origin: string;
  region: string;
  invokeArn: string;
};

export function planProspectusAuthorize(enabled: boolean, environment: Record<string, string | undefined>): ProspectusAuthorizePlan | undefined {
  if (!enabled) return undefined;
  const text = (environment.PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT ?? "").trim();
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    throw new Error("Prospectus authorization needs PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT, the accounts API stage URL.");
  }
  const host = EXECUTE_API_HOST.exec(url.host);
  if (url.protocol !== "https:" || !host || url.pathname !== PROSPECTUS_STAGE_PATH || url.search !== "" || url.hash !== "" || url.username !== "") {
    throw new Error(`Prospectus authorization needs PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT to be https://<id>.execute-api.<region>.amazonaws.com${PROSPECTUS_STAGE_PATH}, got ${text}.`);
  }
  return {
    endpoint: url.toString(),
    origin: url.origin,
    region: host[2],
    invokeArn: `arn:aws:execute-api:${host[2]}:*:${host[1]}/api/POST/v1/accounts/*/authorize`,
  };
}

/** Schema definitions that replace the unguarded ones: the same mutations with the Prospectus function first in each pipeline. */
export function prospectusAuthorizeSchemaDefinitions(): Record<string, unknown> {
  return { ...buildMessageActionsSchemaDefinitions(true), ...buildProfileActionsSchemaDefinitions(true) };
}

const AUTHORIZING_FUNCTIONS = ["contentActions", "categoryAction", "procedureAction"] as const;

export function wireProspectusAuthorize(backend: any, plan: ProspectusAuthorizePlan): void {
  const invoke = new PolicyStatement({ effect: Effect.ALLOW, actions: ["execute-api:Invoke"], resources: [plan.invokeArn] });
  const dataSource = backend.data.addHttpDataSource(PROSPECTUS_DATA_SOURCE_NAME, plan.origin, {
    authorizationConfig: { signingRegion: plan.region, signingServiceName: "execute-api" },
  });
  dataSource.grantPrincipal.addToPrincipalPolicy(invoke);
  for (const name of AUTHORIZING_FUNCTIONS) {
    backend[name].addEnvironment("PAPYRUS_PROSPECTUS_AUTHORIZE", "true");
    backend[name].addEnvironment("PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT", plan.endpoint);
    (backend[name].resources.lambda as LambdaFunction).addToRolePolicy(invoke);
  }
}
