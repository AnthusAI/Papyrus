/**
 * Cognito pre-token-generation trigger, event version 2 (PPY-0bb0fd). On every sign-in and refresh it adds the tenant role
 * claims (claims.ts) to the access token and the ID token, beside the person's Cognito groups, which it never touches.
 * It reads only the TenantSelection and TenantMembership rows of this stack, never Prospectus. A failed read fails the
 * token request: a guessed answer would grant or withhold access without anyone knowing.
 */
import { getLambdaDataClient, LAMBDA_DATA_AUTH_MODE } from "../shared/lambda-data-client";
import { buildTenantClaims, claimEnvironment, type ItemReader, type Row } from "./claims";

export type PreTokenGenerationV2Event = {
  request: {
    userAttributes: Record<string, string>;
    groupConfiguration?: { groupsToOverride?: string[] };
  };
  response: {
    claimsAndScopeOverrideDetails?: {
      idTokenGeneration?: { claimsToAddOrOverride?: Record<string, string> };
      accessTokenGeneration?: { claimsToAddOrOverride?: Record<string, string> };
    };
  };
};

export function createHandler(read: ItemReader, environment: () => Record<string, string | undefined> = () => process.env) {
  return async function handler<Event extends PreTokenGenerationV2Event>(event: Event): Promise<Event> {
    const userSub = event.request.userAttributes.sub;
    if (!userSub) throw new Error("The token event carries no sub, so no tenant can be chosen for it.");
    const claims = await buildTenantClaims(
      claimEnvironment(environment()),
      { userSub, groups: event.request.groupConfiguration?.groupsToOverride ?? [] },
      read,
    );
    if (Object.keys(claims).length > 0) {
      event.response.claimsAndScopeOverrideDetails = {
        ...event.response.claimsAndScopeOverrideDetails,
        idTokenGeneration: { claimsToAddOrOverride: claims },
        accessTokenGeneration: { claimsToAddOrOverride: claims },
      };
    }
    return event;
  };
}

/**
 * One GetItem through the stack's own data API with the function's IAM role (the same wiring as manage-user-role). The function
 * sits in the auth stack, which the data API's user pool depends on, so it cannot name the tables directly without a cycle
 * between the two stacks; the schema grants it query access instead (`functionGrants` in amplify/data/schema.ts).
 */
const readDataItem: ItemReader = async (model, id) => {
  const client = await getLambdaDataClient();
  const options = { authMode: LAMBDA_DATA_AUTH_MODE };
  const { data, errors } = model === "TenantSelection" ? await client.models.TenantSelection.get({ id }, options) : await client.models.TenantMembership.get({ id }, options);
  if (errors?.length) throw new Error(`Reading ${model} ${id} failed: ${errors.map((error: { message?: string }) => error.message).join("; ")}`);
  return (data as Row | null | undefined) ?? null;
};

export const handler = createHandler(readDataItem);
