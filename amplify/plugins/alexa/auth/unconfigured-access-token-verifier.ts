import type { AccessTokenVerifier } from "../contracts";

/** The placeholder verifier: every token is refused, so a linked-account feature cannot work by accident. */
export const unconfiguredAccessTokenVerifier: AccessTokenVerifier = {
  async verify() {
    return { ok: false, reason: "access token verification is not implemented" };
  },
};
