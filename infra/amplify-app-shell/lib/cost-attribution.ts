import type { IConstruct } from "constructs";
import { applyCostTags } from "./cost-accounting-cdk";
import { costTags, OWNER, SHARED, type CostTagConfiguration } from "./cost-accounting-tags";

/**
 * Prospectus cost accounting for Papyrus (Prospectus docs/COST_ACCOUNTING.md). Every resource a dedicated site's
 * stacks create is tagged account `owner`, app `papyrus` and the site ID as the deployment: Prospectus finds the
 * owning Account from whichever Account holds the active papyrus-<site> entitlement, and records the cost as
 * overhead when none does (Ryan, 2026-11-09). Resources that serve many sites are tagged `shared`. No Account ID is
 * configured anywhere in Papyrus.
 */

export const SITE_ID_VARIABLE = "PAPYRUS_SITE_ID";

/** The cost tags of a dedicated site's resources. */
export const siteCostTagConfiguration = (siteId: string): CostTagConfiguration => ({ account: OWNER, app: "papyrus", deployment: siteId });

/** The cost tags of a resource that serves many Papyrus sites; Prospectus splits its cost by reported usage. */
export const SHARED_COST_TAGS: CostTagConfiguration = { account: SHARED, app: "papyrus" };

/**
 * The tags themselves, for a CDK app outside this package (infra/scheduled-jobs), which applies them with its own
 * aws-cdk-lib: two copies of the library must not share one Tags aspect.
 */
export const siteCostTags = (siteId: string) => costTags(siteCostTagConfiguration(siteId));
export const sharedCostTags = () => costTags(SHARED_COST_TAGS);

export function applySiteCostTags(scope: IConstruct, siteId: string): Record<string, string> {
  return applyCostTags(scope, siteCostTagConfiguration(siteId));
}

export function applySharedCostTags(scope: IConstruct): Record<string, string> {
  return applyCostTags(scope, SHARED_COST_TAGS);
}

/** The Amplify branch variable that tells the backend build its site ID, its cost deployment (amplify/cost-attribution.ts). */
export const costAttributionBranchVariables = (siteId: string): Record<string, string> => ({ [SITE_ID_VARIABLE]: siteId });
