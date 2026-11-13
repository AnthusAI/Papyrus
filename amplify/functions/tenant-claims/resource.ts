import { defineFunction } from "@aws-amplify/backend";

/**
 * Cognito's pre-token-generation trigger (PPY-0bb0fd). `amplify/auth/tenant-session-claims.ts` rewires it to event version 2
 * (so the claims land on the access token) and gives it read access to two tenancy tables.
 */
export const tenantClaims = defineFunction({
  name: "papyrus-tenant-claims",
  entry: "./handler.ts",
  timeoutSeconds: 5,
  memoryMB: 256,
  resourceGroupName: "auth",
});
