import { CognitoJwtVerifier } from "aws-jwt-verify";
import type { Jwks } from "aws-jwt-verify/jwk";
import type { AccessTokenResult, AccessTokenVerifier } from "../contracts";

/** The Lambda environment contract for account linking; the Cognito wiring step sets both. */
export const USER_POOL_ID_ENV = "PAPYRUS_ALEXA_USER_POOL_ID";
export const CLIENT_ID_ENV = "PAPYRUS_ALEXA_CLIENT_ID";

type AccessTokenVerifierEnvironment = Record<string, string | undefined>;

// Module scope: a warm Lambda keeps the verifier, and so its fetched JWKS, across invocations.
const verifiers = new Map<string, ReturnType<typeof newVerifier>>();

function newVerifier(userPoolId: string, clientId: string) {
  return CognitoJwtVerifier.create({ userPoolId, clientId, tokenUse: "access" });
}

function cachedVerifier(userPoolId: string, clientId: string, jwks?: Jwks) {
  const key = `${userPoolId}|${clientId}`;
  let verifier = verifiers.get(key);
  if (!verifier) {
    verifier = newVerifier(userPoolId, clientId);
    if (jwks) verifier.cacheJwks(jwks);
    verifiers.set(key, verifier);
  }
  return verifier;
}

/**
 * Verifies a Cognito access token (signature, issuer, expiry, `token_use` access, `client_id`). The pool and client come from the
 * environment at call time; without them every token is refused with reason "not-configured".
 * `jwks` primes the cache (tests only; production fetches the pool's JWKS on first use).
 */
export function createCognitoAccessTokenVerifier(
  environment: AccessTokenVerifierEnvironment = process.env,
  jwks?: Jwks,
): AccessTokenVerifier {
  return {
    async verify(accessToken: string): Promise<AccessTokenResult> {
      const userPoolId = environment[USER_POOL_ID_ENV];
      const clientId = environment[CLIENT_ID_ENV];
      if (!userPoolId || !clientId) return { ok: false, reason: "not-configured" };
      try {
        const claims = await cachedVerifier(userPoolId, clientId, jwks).verify(accessToken);
        return { ok: true, token: { subject: claims.sub, claims: claims as Record<string, unknown> } };
      } catch (error) {
        return { ok: false, reason: error instanceof Error ? error.message : "invalid access token" };
      }
    },
  };
}
