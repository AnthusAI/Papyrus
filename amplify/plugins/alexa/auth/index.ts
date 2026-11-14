import type { AlexaConfig } from "../config";
import type { AccessTokenVerifier } from "../contracts";
import { createCognitoAccessTokenVerifier } from "./cognito-access-token-verifier";

/**
 * The seam for access token validation. `undefined` when the site did not turn account linking on. The verifier reads its Cognito pool and client
 * from the Lambda environment and refuses every token as "not-configured" until the wiring sets them.
 */
export function createAccessTokenVerifier(config: AlexaConfig): AccessTokenVerifier | undefined {
  return config.accountLinking ? createCognitoAccessTokenVerifier() : undefined;
}

export { linkAccountResponse, linkedUser, requireLinkedUser, LINK_ACCOUNT_SPEECH, type LinkedUser } from "./linked-user";
