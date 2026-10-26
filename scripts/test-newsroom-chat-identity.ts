import assert from "node:assert/strict";
import { SignJWT, exportJWK, generateKeyPair } from "jose";
import { SimpleJwksCache } from "aws-jwt-verify/jwk";
import { NextRequest } from "next/server";
import { newsroomChatIdentityResolver } from "../lib/newsroom-chat-identity";
import { createNewsroomChatFetch } from "../lib/newsroom-chat-client";
import { handleProspectusSignInStart, handleProspectusSignInCallback } from "../lib/prospectus-sign-in-routes";
import { PROSPECTUS_PENDING_SIGN_IN_COOKIE, PROSPECTUS_SESSION_COOKIE, openProspectusCookie } from "../lib/prospectus-session";
import { ProspectusSiteAccounts, completeProspectusGoogleSignIn, cognitoTokenVerifier } from "../lib/prospectus-site-identity";

async function main() {
  const { privateKey, publicKey } = await generateKeyPair("RS256");
  const jwk = { ...await exportJWK(publicKey), kid: "fixture", alg: "RS256", use: "sig" };
  const cache = new SimpleJwksCache({ fetcher: { fetch: async () => ({ keys: [jwk] }) } as never });
  const pool = "us-east-1_Synthetic";
  const issuer = `https://cognito-idp.us-east-1.amazonaws.com/${pool}`;
  const sign = (claims: Record<string, unknown> = {}, iss = issuer) => new SignJWT({ sub: "editor-a", token_use: "access", client_id: "newsroom-client", "cognito:groups": ["editor"], ...claims })
    .setProtectedHeader({ alg: "RS256", kid: "fixture" }).setIssuer(iss).setExpirationTime("5m").sign(privateKey);
  const resolve = newsroomChatIdentityResolver({ user_pool_id: pool, user_pool_client_id: "newsroom-client" }, cache);
  const request = (token: string) => new NextRequest("https://publication.example/api/auth/prospectus/sign-in?newsroomChat=true&returnTo=%2Fnewsroom%2Fnotifications", { method: "POST", headers: { authorization: `Bearer ${token}`, origin: "https://publication.example" } });
  const token = await sign();
  assert.deepEqual(await resolve(request(token)), { subject: "editor-a" });
  for (const claims of [{ client_id: "other-client" }, { token_use: "id" }, { "cognito:groups": ["reader"] }, { "cognito:groups": [] }]) assert.equal(await resolve(request(await sign(claims))), null);
  assert.equal(await resolve(request(await sign({}, "https://untrusted.example"))), null);
  const expired = await new SignJWT({ sub: "editor-a", token_use: "access", client_id: "newsroom-client", "cognito:groups": ["editor"] }).setProtectedHeader({ alg: "RS256", kid: "fixture" }).setIssuer(issuer).setExpirationTime(1).sign(privateKey);
  assert.equal(await resolve(request(expired)), null);
  assert.equal(await resolve(request(`${token.slice(0, -20)}aaaaaaaaaaaaaaaaaaaa`)), null);

  const secret = "synthetic-newsroom-session-secret-at-least-32-bytes";
  let resolutions = 0;
  const accounts = new ProspectusSiteAccounts(async (operation) => {
    if (operation.path.endsWith("/challenge")) return { challengeId: "challenge", nonce: "challenge-nonce", expiresAt: 2000 };
    resolutions += 1;
    return { person: { id: "canonical-person-a", createdAt: "2026-01-01T00:00:00Z" } };
  });
  const cognitoClient = { userPoolId: pool, clientId: "registered-google-client", hostedUiOrigin: "https://example.auth.us-east-1.amazoncognito.com", redirectUri: "https://publication.example/api/auth/prospectus/callback" };
  const options = { resolveRuntime: async () => ({ accounts, sealingSecret: secret, cognitoClient }), resolveNewsroomIdentity: resolve, environment: { PAPYRUS_SITE_ORIGIN: "https://publication.example" }, nowInSeconds: () => 1000 };
  const start = await handleProspectusSignInStart(request(token), options);
  assert.equal(start.status, 200);
  const sealed = start.cookies.get(PROSPECTUS_PENDING_SIGN_IN_COOKIE)!.value;
  const pending = openProspectusCookie<any>(secret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, sealed, 1000)!;
  assert.equal(pending.newsroomSubject, "editor-a");
  assert.equal(pending.returnPath, "/newsroom/notifications");
  const crossOrigin = request(token);
  crossOrigin.headers.set("origin", "https://other.example");
  assert.equal((await handleProspectusSignInStart(crossOrigin, options)).status, 403);
  const complete = async (subject: string) => {
    const access = await sign({ client_id: cognitoClient.clientId, sub: subject });
    const id = await sign({ token_use: "id", client_id: undefined, aud: cognitoClient.clientId, nonce: pending.nonce, sub: subject });
    return completeProspectusGoogleSignIn({ accounts, cognitoClient, pendingSignIn: pending, returnedState: pending.state, authorizationCode: "synthetic", expectedNewsroomSubject: pending.newsroomSubject, nowInSeconds: 1000,
      verifyCognitoTokens: cognitoTokenVerifier(cognitoClient, cache), fetcher: async () => Response.json({ access_token: access, id_token: id, expires_in: 300 }) });
  };
  await assert.rejects(complete("editor-b"), { code: "newsroom_identity_mismatch" });
  assert.equal(resolutions, 0, "a different Google account cannot resolve or bind a person");
  assert.equal((await complete("editor-a")).person.id, "canonical-person-a");
  assert.equal(resolutions, 1);

  const callbackAccess = await sign({ client_id: cognitoClient.clientId });
  const callbackId = await sign({ token_use: "id", client_id: undefined, aud: cognitoClient.clientId, nonce: pending.nonce });
  const callback = await handleProspectusSignInCallback(new NextRequest(`https://publication.example/api/auth/prospectus/callback?state=${pending.state}&code=synthetic`, { headers: { cookie: `${PROSPECTUS_PENDING_SIGN_IN_COOKIE}=${sealed}` } }), {
    ...options,
    completionOverrides: { verifyCognitoTokens: cognitoTokenVerifier(cognitoClient, cache), fetcher: async () => Response.json({ access_token: callbackAccess, id_token: callbackId, expires_in: 300 }) },
  });
  assert.equal(callback.status, 303);
  assert.equal(callback.headers.get("location"), "https://publication.example/newsroom/notifications");
  const connected = openProspectusCookie<any>(secret, PROSPECTUS_SESSION_COOKIE, callback.cookies.get(PROSPECTUS_SESSION_COOKIE)!.value, 1000)!;
  assert.equal(connected.newsroomSubject, "editor-a");
  assert.equal(connected.personId, "canonical-person-a");
  assert.equal(connected.selectedAccountId, undefined, "connection does not invent publishing Account selection");

  let reads = 0;
  let fetches = 0;
  const authenticatedFetch = createNewsroomChatFetch(async () => `fresh-${++reads}`, async (_input, init) => {
    fetches += 1;
    assert.equal(new Headers(init?.headers).get("authorization"), `Bearer fresh-${reads}`);
    return Response.json({});
  });
  await authenticatedFetch("/api/newsroom/chat/private-channel", { method: "POST" });
  await authenticatedFetch("/api/newsroom/chat/channels/example/messages");
  await assert.rejects(authenticatedFetch("https://other.example/api/newsroom/chat/private-channel"));
  assert.equal(fetches, 2);
  console.log("PASS: verified newsroom JWT, same-subject challenge connection, fresh same-origin credentials");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
