import assert from "node:assert/strict";
import { SignJWT, exportJWK, generateKeyPair } from "jose";
import { SimpleJwksCache } from "aws-jwt-verify/jwk";
import {
  ProspectusAccountsError,
  ProspectusSiteAccounts,
  authorizeSignedInPersonForAccount,
  beginProspectusGoogleSignIn,
  cognitoTokenVerifier,
  completeProspectusGoogleSignIn,
  signedInPersonHasCyclotronLabAccess,
  signedProspectusTransport,
  type ProspectusRequest,
} from "../lib/prospectus-site-identity";

const cognitoClient = {
  hostedUiOrigin: "https://papyrus-p-apyr-us.auth.us-east-1.amazoncognito.com",
  userPoolId: "us-east-1_Synthetic",
  clientId: "googleonlyclient",
  redirectUri: "https://p.apyr.us/api/prospectus/callback",
};

function recordingProspectus(responses: Record<string, unknown>) {
  const requests: ProspectusRequest[] = [];
  const accounts = new ProspectusSiteAccounts(async (request) => {
    requests.push(request);
    const response = responses[`${request.method} ${request.path}`];
    if (response instanceof Error) throw response;
    if (response === undefined) throw new Error(`unexpected ${request.method} ${request.path}`);
    return response;
  });
  return { accounts, requests };
}

function cognitoTokenEndpoint(tokenBody: Record<string, unknown>, status = 200) {
  const exchanges: URLSearchParams[] = [];
  const fetcher = (async (url: URL, init: RequestInit) => {
    assert.equal(url.toString(), `${cognitoClient.hostedUiOrigin}/oauth2/token`);
    exchanges.push(new URLSearchParams(init.body as string));
    return new Response(JSON.stringify(tokenBody), { status });
  }) as unknown as typeof fetch;
  return { fetcher, exchanges };
}

async function main() {
  const challenge = { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 2_000 };
  const { accounts, requests } = recordingProspectus({
    "POST /v1/identities/google/challenge": challenge,
    "POST /v1/identities/google/resolve": { person: { id: "person-1", createdAt: "2026-10-17T00:00:00Z" } },
  });

  const { authorizationUrl, pendingSignIn } = await beginProspectusGoogleSignIn(accounts, cognitoClient);
  const authorization = new URL(authorizationUrl);
  assert.equal(authorization.origin + authorization.pathname, `${cognitoClient.hostedUiOrigin}/oauth2/authorize`);
  assert.equal(authorization.searchParams.get("nonce"), "prospectus-nonce");
  assert.equal(authorization.searchParams.get("identity_provider"), "Google");
  assert.equal(authorization.searchParams.get("client_id"), "googleonlyclient");
  assert.equal(authorization.searchParams.get("code_challenge_method"), "S256");
  assert.equal(authorization.searchParams.get("state"), pendingSignIn.state);
  assert.notEqual(authorization.searchParams.get("code_challenge"), pendingSignIn.codeVerifier);
  assert.equal(requests[0].humanAccessToken, undefined, "the challenge is requested before anyone is signed in");

  const issuedTokens = { access_token: "access-jwt", id_token: "id-jwt", refresh_token: "refresh", expires_in: 3600 };
  const verifiedNonces: string[] = [];
  const verifyCognitoTokens = async (_tokens: unknown, expectedNonce: string) => {
    verifiedNonces.push(expectedNonce);
  };

  const wrongState = cognitoTokenEndpoint(issuedTokens);
  await assert.rejects(
    completeProspectusGoogleSignIn({ accounts, cognitoClient, pendingSignIn, returnedState: "forged", authorizationCode: "code", verifyCognitoTokens, fetcher: wrongState.fetcher, nowInSeconds: 1_000 }),
    (error: ProspectusAccountsError) => error.code === "state_mismatch",
  );
  assert.equal(wrongState.exchanges.length, 0, "a forged state never reaches Cognito");

  const expired = cognitoTokenEndpoint(issuedTokens);
  await assert.rejects(
    completeProspectusGoogleSignIn({ accounts, cognitoClient, pendingSignIn, returnedState: pendingSignIn.state, authorizationCode: "code", verifyCognitoTokens, fetcher: expired.fetcher, nowInSeconds: 2_000 }),
    (error: ProspectusAccountsError) => error.code === "sign_in_expired",
  );
  assert.equal(expired.exchanges.length, 0);

  const rejectedExchange = cognitoTokenEndpoint({ error: "invalid_grant" }, 400);
  await assert.rejects(
    completeProspectusGoogleSignIn({ accounts, cognitoClient, pendingSignIn, returnedState: pendingSignIn.state, authorizationCode: "code", verifyCognitoTokens, fetcher: rejectedExchange.fetcher, nowInSeconds: 1_000 }),
    (error: ProspectusAccountsError) => error.code === "code_exchange_failed",
  );

  const accepted = cognitoTokenEndpoint(issuedTokens);
  const signedIn = await completeProspectusGoogleSignIn({
    accounts, cognitoClient, pendingSignIn, returnedState: pendingSignIn.state, authorizationCode: "code", verifyCognitoTokens, fetcher: accepted.fetcher, nowInSeconds: 1_000,
  });
  assert.equal(accepted.exchanges[0].get("code_verifier"), pendingSignIn.codeVerifier);
  assert.equal(accepted.exchanges[0].get("grant_type"), "authorization_code");
  assert.equal(accepted.exchanges[0].get("client_secret"), null);
  assert.deepEqual(verifiedNonces, ["prospectus-nonce"]);
  const resolveRequest = requests.find((request) => request.path === "/v1/identities/google/resolve");
  assert.deepEqual(resolveRequest, { path: "/v1/identities/google/resolve", method: "POST", body: { challengeId: "challenge-1" }, humanAccessToken: "access-jwt", identityToken: "id-jwt" });
  assert.deepEqual(signedIn, { person: { id: "person-1", createdAt: "2026-10-17T00:00:00Z" }, accessToken: "access-jwt", refreshToken: "refresh", accessTokenExpiresAt: 4_600 });
  assert.equal("idToken" in signedIn, false, "the identity token is discarded once Prospectus has resolved the person");

  const allowed = { allowed: true, accountId: "account-a", personId: "person-1", product: "papyrus-p-apyr-us", role: "member", operation: "console:read", revision: 3 };
  const authorized = recordingProspectus({
    "GET /v1/identities/me": { person: { id: "person-1", createdAt: "x" } },
    "POST /v1/accounts/account-a/authorize": allowed,
  });
  assert.deepEqual(await authorizeSignedInPersonForAccount(authorized.accounts, "access-jwt", "account-a", "console:read"), allowed);
  assert.deepEqual(authorized.requests.map((request) => request.humanAccessToken), ["access-jwt", "access-jwt"]);

  const unknownPerson = recordingProspectus({ "GET /v1/identities/me": { person: null } });
  await assert.rejects(authorizeSignedInPersonForAccount(unknownPerson.accounts, "access-jwt", "account-a", "console:read"), (error: ProspectusAccountsError) => error.status === 401);
  assert.equal(unknownPerson.requests.length, 1, "an unknown person never reaches account authorization");

  const otherPerson = recordingProspectus({
    "GET /v1/identities/me": { person: { id: "person-1", createdAt: "x" } },
    "POST /v1/accounts/account-a/authorize": { ...allowed, personId: "person-2" },
  });
  await assert.rejects(authorizeSignedInPersonForAccount(otherPerson.accounts, "access-jwt", "account-a", "console:read"), (error: ProspectusAccountsError) => error.status === 403);

  const deniedByProspectus = recordingProspectus({
    "GET /v1/identities/me": { person: { id: "person-1", createdAt: "x" } },
    "POST /v1/accounts/account-a/authorize": new ProspectusAccountsError(403, "forbidden", "Not a member."),
  });
  await assert.rejects(authorizeSignedInPersonForAccount(deniedByProspectus.accounts, "access-jwt", "account-a", "console:write"), (error: ProspectusAccountsError) => error.status === 403);

  const directory = (accountProducts: Array<{ product: string; status: "active" | "disabled" }>, person: unknown = { id: "person-1", createdAt: "x" }) =>
    recordingProspectus({ "GET /v1/account-directory": { person, accounts: [{ id: "account-a", name: "A", role: "member", products: accountProducts }] } }).accounts;
  assert.equal(await signedInPersonHasCyclotronLabAccess(directory([{ product: "cyclotron", status: "active" }]), "access-jwt"), true);
  assert.equal(await signedInPersonHasCyclotronLabAccess(directory([{ product: "cyclotron", status: "disabled" }]), "access-jwt"), false);
  assert.equal(await signedInPersonHasCyclotronLabAccess(directory([{ product: "papyrus-p-apyr-us", status: "active" }]), "access-jwt"), false);
  assert.equal(await signedInPersonHasCyclotronLabAccess(directory([{ product: "cyclotron", status: "active" }], null), "access-jwt"), false);

  const signedRequests: Array<{ url: string; init: RequestInit }> = [];
  const transport = signedProspectusTransport({
    endpoint: "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/",
    region: "us-east-1",
    runtimeCredentials: async () => ({ accessKeyId: "ASIASYNTHETIC", secretAccessKey: "synthetic", sessionToken: "session" }),
    fetcher: (async (url: URL, init: RequestInit) => {
      signedRequests.push({ url: url.toString(), init });
      return new Response(JSON.stringify({ person: null }), { status: 200 });
    }) as unknown as typeof fetch,
  });
  await new ProspectusSiteAccounts(transport).currentPerson("access-jwt");
  assert.equal(signedRequests[0].url, "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/v1/identities/me");
  const signedHeaders = signedRequests[0].init.headers as Record<string, string>;
  assert.match(signedHeaders.authorization, /^AWS4-HMAC-SHA256 .*SignedHeaders=.*x-prospectus-human-token/);
  assert.equal(signedHeaders["x-amz-security-token"], "session");
  assert.equal(signedRequests[0].init.redirect, "error");

  // The retired-subjects poll sends a query string; it must be inside the signature API Gateway verifies.
  const pollRequests: Array<{ url: string; headers: Record<string, string> }> = [];
  const pollCredentials = { accessKeyId: "ASIASYNTHETIC", secretAccessKey: "synthetic", sessionToken: "session" };
  const pollAccounts = new ProspectusSiteAccounts(signedProspectusTransport({
    endpoint: "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/",
    region: "us-east-1",
    runtimeCredentials: async () => pollCredentials,
    fetcher: (async (url: URL, init: RequestInit) => {
      pollRequests.push({ url: url.toString(), headers: init.headers as Record<string, string> });
      return new Response(JSON.stringify({ retired: [], cursor: "c2", more: false }), { status: 200 });
    }) as unknown as typeof fetch,
  }));
  assert.deepEqual(await pollAccounts.retiredSiteSubjects("cursor=/1+"), { retired: [], cursor: "c2", more: false });
  await pollAccounts.retiredSiteSubjects();
  assert.equal(pollRequests[0].url, "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/v1/accounts/site-subjects/retired?since=cursor%3D%2F1%2B");
  assert.equal(pollRequests[1].url, "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/v1/accounts/site-subjects/retired");
  {
    const { SignatureV4 } = await import("@smithy/signature-v4");
    const { HttpRequest } = await import("@smithy/protocol-http");
    const { Sha256 } = await import("@aws-crypto/sha256-js");
    const sentAt = pollRequests[0].headers["x-amz-date"];
    const signingDate = new Date(`${sentAt.slice(0, 4)}-${sentAt.slice(4, 6)}-${sentAt.slice(6, 8)}T${sentAt.slice(9, 11)}:${sentAt.slice(11, 13)}:${sentAt.slice(13, 15)}Z`);
    const signer = new SignatureV4({ service: "execute-api", region: "us-east-1", credentials: pollCredentials, sha256: Sha256 });
    const base = { protocol: "https:", hostname: "abc123defg.execute-api.us-east-1.amazonaws.com", path: "/api/v1/accounts/site-subjects/retired", method: "GET", headers: { host: "abc123defg.execute-api.us-east-1.amazonaws.com" } };
    const withQuery = await signer.sign(new HttpRequest({ ...base, query: { since: "cursor=/1+" } }), { signingDate });
    const withoutQuery = await signer.sign(new HttpRequest(base), { signingDate });
    assert.equal(pollRequests[0].headers.authorization, withQuery.headers.authorization, "the signature covers the query string");
    assert.notEqual(pollRequests[0].headers.authorization, withoutQuery.headers.authorization);
  }

  const staticKeyTransport = signedProspectusTransport({
    endpoint: "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/",
    region: "us-east-1",
    runtimeCredentials: async () => ({ accessKeyId: "AKIASTATIC", secretAccessKey: "static" }),
    fetcher: (async () => { throw new Error("must not send"); }) as unknown as typeof fetch,
  });
  await assert.rejects(new ProspectusSiteAccounts(staticKeyTransport).currentPerson("access-jwt"), /static access keys are refused/);
  assert.throws(() => signedProspectusTransport({ endpoint: "http://abc123defg.execute-api.us-east-1.amazonaws.com/api/", region: "us-east-1" }), /HTTPS/);

  const failing = signedProspectusTransport({
    endpoint: "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/",
    region: "us-east-1",
    runtimeCredentials: async () => ({ accessKeyId: "ASIASYNTHETIC", secretAccessKey: "synthetic", sessionToken: "session" }),
    fetcher: (async () => new Response(JSON.stringify({ error: "forbidden", message: "Wrong product." }), { status: 403 })) as unknown as typeof fetch,
  });
  await assert.rejects(new ProspectusSiteAccounts(failing).currentPerson("access-jwt"), (error: ProspectusAccountsError) => error.status === 403 && error.code === "forbidden");

  const { privateKey, publicKey } = await generateKeyPair("RS256");
  const signingKey = { ...(await exportJWK(publicKey)), kid: "synthetic-key", alg: "RS256", use: "sig" };
  const issuer = `https://cognito-idp.us-east-1.amazonaws.com/${cognitoClient.userPoolId}`;
  const signingKeyCache = new SimpleJwksCache({ fetcher: { fetch: async () => ({ keys: [signingKey] }) } as never });
  const cognitoToken = (claims: Record<string, unknown>) =>
    new SignJWT({ token_use: "access", client_id: cognitoClient.clientId, sub: "pool-sub", ...claims })
      .setProtectedHeader({ alg: "RS256", kid: "synthetic-key" })
      .setIssuer(issuer)
      .setIssuedAt()
      .setExpirationTime("5m")
      .sign(privateKey);
  const identityToken = (claims: Record<string, unknown>) =>
    cognitoToken({ token_use: "id", client_id: undefined, aud: cognitoClient.clientId, nonce: "prospectus-nonce", ...claims });
  const verifyRealTokens = cognitoTokenVerifier(cognitoClient, signingKeyCache);
  const tokenPair = async (identityClaims: Record<string, unknown> = {}, accessClaims: Record<string, unknown> = {}) => ({
    accessToken: await cognitoToken(accessClaims),
    idToken: await identityToken(identityClaims),
    expiresInSeconds: 300,
  });
  await verifyRealTokens(await tokenPair(), "prospectus-nonce");
  await assert.rejects(verifyRealTokens(await tokenPair({ nonce: "other-nonce" }), "prospectus-nonce"), (error: ProspectusAccountsError) => error.code === "nonce_mismatch");
  await assert.rejects(verifyRealTokens(await tokenPair({ sub: "other-sub" }), "prospectus-nonce"), (error: ProspectusAccountsError) => error.code === "token_pair_mismatch");
  await assert.rejects(verifyRealTokens(await tokenPair({}, { client_id: "emailclient" }), "prospectus-nonce"), /client/i);
  await assert.rejects(verifyRealTokens(await tokenPair({ aud: "emailclient" }), "prospectus-nonce"), /aud|audience|client/i);

  console.log("prospectus site identity: challenge-bound sign-in, account authorization, Lab access and SigV4 transport: ok");
}

void main().catch((error) => {
  console.error(error);
  process.exit(1);
});
