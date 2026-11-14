import { defineBackend } from "@aws-amplify/backend";
import { ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { auth } from "./auth/resource";
import { data } from "./data/resource";
import { preTokenGeneration } from "./auth/functions";

const backend = defineBackend({ auth, data, preTokenGeneration });

// V2 pre-token generation (can change the access token too) needs the Essentials feature plan.
const cfnUserPool = backend.auth.resources.cfnResources.cfnUserPool;
cfnUserPool.userPoolTier = process.env.SPIKE_POOL_TIER ?? "ESSENTIALS";

// Wire the pre-token Lambda by hand as V2 (Amplify's own trigger wiring is V1, ID token only).
const fn = backend.preTokenGeneration.resources.lambda;
cfnUserPool.addPropertyOverride("LambdaConfig.PreTokenGenerationConfig", {
  LambdaArn: fn.functionArn,
  LambdaVersion: process.env.SPIKE_TRIGGER_VERSION ?? "V2_0",
});
fn.addPermission("CognitoInvokePreToken", {
  principal: new ServicePrincipal("cognito-idp.amazonaws.com"),
  sourceArn: backend.auth.resources.userPool.userPoolArn,
});
