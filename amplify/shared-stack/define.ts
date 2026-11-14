import type { PapyrusSiteBackendConfig } from "../site-backend-config";
import { sharedTierPlan, type SharedTier } from "./names";

/**
 * The backend configuration of a shared stack: tenancy mode shared on the tier, a projection publication with no site's
 * files, and none of the features that belong to one site's mailbox, chat workspace or backups. Nothing else is configured;
 * a tenant's own settings live in the site store (PPY-ee1e02), never in this file.
 */
export function sharedStackBackendConfig(tier: SharedTier): PapyrusSiteBackendConfig {
  return {
    brandId: sharedTierPlan(tier).stackPrefix,
    productionAppId: "",
    tenancy: { mode: "shared", tier },
    publication: { kind: "s3-projection", reprojectOnDeploy: false },
    features: { inboundEmail: false, slack: false, storageBackups: false, cliRemoteLogin: false, cliOnFederationClient: false },
  };
}
