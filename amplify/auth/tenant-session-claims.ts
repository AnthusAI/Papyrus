import type { CfnUserPool } from "aws-cdk-lib/aws-cognito";
import type { IFunction } from "aws-cdk-lib/aws-lambda";
import { TENANCY_MODELS_ENVIRONMENT_VARIABLE } from "../functions/tenant-claims/claims";

/** The Cognito feature plan that supports pre-token-generation event version 2 (access-token claims). Lite does not. */
export const TENANT_CLAIMS_USER_POOL_TIER = "ESSENTIALS";
/** The pre-token-generation event version that customises the access token as well as the ID token. */
export const TENANT_CLAIMS_TRIGGER_VERSION = "V2_0";

/**
 * Wire the tenant claims function as the pool's pre-token-generation trigger at event version 2 (PPY-0bb0fd).
 *
 * Amplify's `triggers.preTokenGeneration` wires version 1, which customises only the ID token, and the Amplify data client
 * sends the access token. The CDK escape hatch below moves the same function to `PreTokenGenerationConfig` at `V2_0` and
 * removes the version 1 entry (the two must not both be set). Version 2 needs the Cognito Essentials plan, so the pool's
 * `UserPoolTier` is set to it; that is a plan and cost change for every site that deploys this.
 *
 * `tenancyModelsDeployed` says whether TenantMembership and TenantSelection exist (the `tenancy` model group is deployed; a
 * bootstrap deploy leaves it out). When they do not, the function reads nothing and emits only a dedicated stack's group claims.
 */
export function applyTenantSessionClaims(cfnUserPool: CfnUserPool, trigger: IFunction, tenancyModelsDeployed: boolean): void {
  cfnUserPool.userPoolTier = TENANT_CLAIMS_USER_POOL_TIER;
  cfnUserPool.addPropertyDeletionOverride("LambdaConfig.PreTokenGeneration");
  cfnUserPool.addPropertyOverride("LambdaConfig.PreTokenGenerationConfig", {
    LambdaArn: trigger.functionArn,
    LambdaVersion: TENANT_CLAIMS_TRIGGER_VERSION,
  });
  if (tenancyModelsDeployed) {
    (trigger as IFunction & { addEnvironment(key: string, value: string): unknown }).addEnvironment(TENANCY_MODELS_ENVIRONMENT_VARIABLE, "true");
  }
}
