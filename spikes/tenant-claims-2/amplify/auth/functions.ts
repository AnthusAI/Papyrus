import { defineFunction } from "@aws-amplify/backend";

// Memberships for the spike only: email -> tenant -> roles. The real design reads TenantMembership.
const MEMBERSHIPS = JSON.stringify({
  "alpha-editor@example.test": { alpha: ["editor"] },
  "beta-editor@example.test": { beta: ["editor"] },
  "alpha-member@example.test": { alpha: ["member"] },
  "both-editor@example.test": { alpha: ["editor"], beta: ["editor"] },
});

export const preTokenGeneration = defineFunction({
  name: "spike-pre-token",
  entry: "../functions/pre-token/handler.ts",
  environment: { MEMBERSHIPS },
  resourceGroupName: "auth",
});
export const defineAuthChallenge = defineFunction({ name: "spike-define-challenge", entry: "../functions/challenge/define.ts", resourceGroupName: "auth" });
export const createAuthChallenge = defineFunction({ name: "spike-create-challenge", entry: "../functions/challenge/create.ts", resourceGroupName: "auth" });
export const verifyAuthChallengeResponse = defineFunction({
  name: "spike-verify-challenge",
  entry: "../functions/challenge/verify.ts",
  environment: { SPIKE_SECRET: process.env.SPIKE_SECRET ?? "unset" },
  resourceGroupName: "auth",
});
