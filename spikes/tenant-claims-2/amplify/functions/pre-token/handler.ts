import type { PreTokenGenerationV2TriggerHandler } from "aws-lambda";

const MEMBERSHIPS = JSON.parse(process.env.MEMBERSHIPS ?? "{}") as Record<string, Record<string, string[]>>;

// One claim per role, holding the tenant id the session acts for (design note, "Editors and agents").
export const handler: PreTokenGenerationV2TriggerHandler = async (event) => {
  const email = event.request.userAttributes.email;
  const tenant = event.request.clientMetadata?.tenant;
  const roles = (tenant && MEMBERSHIPS[email]?.[tenant]) || [];
  const claims: Record<string, string> = {};
  for (const role of roles) claims[`papyrus_tenant_${role}`] = tenant as string;
  event.response = {
    claimsAndScopeOverrideDetails: {
      idTokenGeneration: { claimsToAddOrOverride: claims },
      accessTokenGeneration: { claimsToAddOrOverride: claims },
    },
  };
  return event;
};
