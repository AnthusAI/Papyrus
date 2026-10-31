/**
 * Alexa account linking: access token verification and the signed-in helpers, against a fake JWKS (an RSA key generated here).
 * Run with no argument for everything, or with one behaviour name (the Gherkin steps do this); each prints `{"behaviour": ...}`.
 */
import assert from "node:assert/strict";
import { createSign, generateKeyPairSync, type KeyObject } from "node:crypto";
import type { HandlerInput } from "ask-sdk-core";
import { ResponseFactory } from "ask-sdk-core";
import type { Jwks } from "aws-jwt-verify/jwk";
import { resolveAlexaConfig } from "../amplify/plugins/alexa/config";
import { createAccessTokenVerifier, linkAccountResponse, linkedUser, requireLinkedUser } from "../amplify/plugins/alexa/auth";
import { CLIENT_ID_ENV, createCognitoAccessTokenVerifier, USER_POOL_ID_ENV } from "../amplify/plugins/alexa/auth/cognito-access-token-verifier";

const POOL = "us-east-1_TestPool1";
const CLIENT = "test-client-linked";
const ISSUER = `https://cognito-idp.us-east-1.amazonaws.com/${POOL}`;
const KID = "test-key-1";

const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const other = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwks: Jwks = { keys: [{ ...(publicKey.export({ format: "jwk" }) as object), kid: KID, alg: "RS256", use: "sig" } as Jwks["keys"][number]] };

const b64 = (value: object | Buffer) => Buffer.from(value instanceof Buffer ? value : JSON.stringify(value)).toString("base64url");
function sign(claims: Record<string, unknown>, key: KeyObject = privateKey): string {
  const now = Math.floor(Date.now() / 1000);
  const body = {
    sub: "user-sub-1", iss: ISSUER, client_id: CLIENT, token_use: "access", scope: "openid", username: "google_123",
    "cognito:groups": ["editors", "admins"], iat: now - 10, exp: now + 3600, ...claims,
  };
  const signingInput = `${b64({ alg: "RS256", kid: KID, typ: "JWT" })}.${b64(body)}`;
  return `${signingInput}.${b64(createSign("RSA-SHA256").update(signingInput).sign(key))}`;
}

const env = { [USER_POOL_ID_ENV]: POOL, [CLIENT_ID_ENV]: CLIENT };
const verifier = createCognitoAccessTokenVerifier(env, jwks);

function input(accessToken?: string): HandlerInput {
  const user = accessToken ? { userId: "amzn-user", accessToken } : { userId: "amzn-user" };
  return {
    requestEnvelope: { context: { System: { user } }, request: { type: "LaunchRequest" } },
    responseBuilder: ResponseFactory.init(),
  } as unknown as HandlerInput;
}

const behaviours: Record<string, () => Promise<void>> = {
  "a valid linked token is accepted": async () => {
    const result = await verifier.verify(sign({}));
    assert.ok(result.ok);
    assert.equal(result.token.subject, "user-sub-1");
    const user = await linkedUser(input(sign({ email: "reader@example.invalid" })), verifier);
    assert.deepEqual(user, { sub: "user-sub-1", username: "google_123", email: "reader@example.invalid", groups: ["editors", "admins"] });
  },
  "a request without a token is not signed in": async () => {
    assert.equal(await linkedUser(input(), verifier), null);
    assert.equal(await linkedUser(input(sign({})), undefined), null);
  },
  "an expired token is refused": async () => {
    const result = await verifier.verify(sign({ exp: Math.floor(Date.now() / 1000) - 60 }));
    assert.equal(result.ok, false);
    assert.equal(await linkedUser(input(sign({ exp: 1 })), verifier), null);
  },
  "a token for another client is refused": async () => {
    assert.equal((await verifier.verify(sign({ client_id: "someone-else" }))).ok, false);
  },
  "a token from another issuer is refused": async () => {
    const result = await verifier.verify(sign({ iss: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other" }));
    assert.equal(result.ok, false);
  },
  "an id token is refused as an access token": async () => {
    assert.equal((await verifier.verify(sign({ token_use: "id", aud: CLIENT }))).ok, false);
  },
  "a revoked or forged token is refused": async () => {
    // Cognito rotates keys and signs out globally; locally both read as an invalid or expired token. A token whose signature is not the pool's key is invalid.
    assert.equal((await verifier.verify(sign({}, other.privateKey))).ok, false);
    assert.equal(await linkedUser(input(sign({}, other.privateKey)), verifier), null);
    assert.equal((await verifier.verify("not.a.jwt")).ok, false);
  },
  "without configuration every token is refused as not configured": async () => {
    const result = await createCognitoAccessTokenVerifier({}, jwks).verify(sign({}));
    assert.deepEqual(result, { ok: false, reason: "not-configured" });
    const partial = await createCognitoAccessTokenVerifier({ [USER_POOL_ID_ENV]: POOL }, jwks).verify(sign({}));
    assert.deepEqual(partial, { ok: false, reason: "not-configured" });
  },
  "the verifier exists only when account linking is on": async () => {
    const base = { invocationName: "test site", siteOrigin: "https://example.invalid" };
    assert.equal(createAccessTokenVerifier(resolveAlexaConfig({ ...base, accountLinking: false } as never)), undefined);
    assert.ok(createAccessTokenVerifier(resolveAlexaConfig({ ...base, accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR" } as never)));
  },
  "a signed-out intent gets a link account card": async () => {
    const response = linkAccountResponse(input());
    assert.equal(response.card?.type, "LinkAccount");
    assert.match(String((response.outputSpeech as { ssml: string }).ssml), /open the Alexa app or scan the code on your screen to link your account/);
    const gated = await requireLinkedUser(input(), verifier, () => assert.fail("must not run"));
    assert.equal(gated.card?.type, "LinkAccount");
    const signedIn = await requireLinkedUser(input(sign({})), verifier, (user) => input().responseBuilder.speak(`hi ${user.username}`).getResponse());
    assert.equal(signedIn.card, undefined);
  },
};

async function main() {
  const wanted = process.argv[2];
  const names = wanted ? [wanted] : Object.keys(behaviours);
  for (const name of names) {
    assert.ok(behaviours[name], `unknown behaviour: ${name}`);
    await behaviours[name]();
    console.log(JSON.stringify({ behaviour: name }));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
