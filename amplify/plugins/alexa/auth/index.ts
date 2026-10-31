import type { AlexaConfig } from "../config";
import type { AccessTokenVerifier } from "../contracts";
import { unconfiguredAccessTokenVerifier } from "./unconfigured-access-token-verifier";

/**
 * The seam for access token validation. `undefined` when the site did not turn account linking on. A real verifier is a file in
 * this folder (it may use `aws-jwt-verify`); switch to it by changing the return line.
 */
export function createAccessTokenVerifier(config: AlexaConfig): AccessTokenVerifier | undefined {
  return config.accountLinking ? unconfiguredAccessTokenVerifier : undefined;
}
