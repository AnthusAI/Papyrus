/**
 * Set to "true" by the site backend when the `tenancy` model group is deployed (a bootstrap deploy leaves it out), which is
 * when TenantMembership and TenantSelection exist to be read. Without it the function reads no table.
 * Its own file because the backend definition (amplify/auth/tenant-session-claims.ts) needs it and the package compiles that
 * side separately from the handler side (packages/papyrus/scripts/stage.mjs).
 */
export const TENANCY_MODELS_ENVIRONMENT_VARIABLE = "PAPYRUS_TENANT_RECORDS_DEPLOYED";
