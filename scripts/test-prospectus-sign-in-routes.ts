import assert from "node:assert/strict";
import { App, SecretValue, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { UserPool, UserPoolIdentityProviderGoogle } from "aws-cdk-lib/aws-cognito";
import { NextRequest } from "next/server";
import {
  PROSPECTUS_SIGN_IN_CALLBACK_PATH,
  addProspectusGoogleOnlyClient,
  prospectusSignInCallbackUrls,
  prospectusSignInLogoutUrls,
} from "../amplify/auth/prospectus-google-client";
import {
  PROSPECTUS_PENDING_SIGN_IN_COOKIE,
  PROSPECTUS_SESSION_COOKIE,
  googleOnlyCognitoClientFromOutputs,
  loadProspectusSessionSealingSecret,
  readSealingSecretFromSsm,
  openProspectusCookie,
  regionOfProspectusAccountsEndpoint,
  resetProspectusSessionSecretCache,
  resolveProspectusSignInRuntime,
  sameSiteReturnPath,
  sealProspectusCookie,
  type ProspectusSignInRuntime,
} from "../lib/prospectus-session";
import {
  currentProspectusPublishingSelection,
  handleProspectusAccountSelection,
  handleProspectusPublishingAccountCreation,
  handleProspectusSessionRead,
  handleProspectusSignInCallback,
  handleProspectusSignInStart,
  handleProspectusSignOut,
  type ProspectusSignInRouteOptions,
} from "../lib/prospectus-sign-in-routes";
import { ProspectusAccountsError, ProspectusSiteAccounts, type ProspectusRequest } from "../lib/prospectus-site-identity";
import { prospectusSiteProduct, publicationCapabilitiesForProspectusRole, publishingAccountsForSite } from "../lib/prospectus-publication-access";

const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const siteOrigin = "https://p.apyr.us";
const amplifyOutputs = {
  auth: { user_pool_id: "us-east-1_Synthetic", oauth: { domain: "papyrus-p-apyr-us.auth.us-east-1.amazoncognito.com" } },
  custom: { prospectusSignIn: { clientId: "googleonlyclient", callbackPath: PROSPECTUS_SIGN_IN_CALLBACK_PATH } },
};
const cognitoClient = googleOnlyCognitoClientFromOutputs(amplifyOutputs, siteOrigin)!;
const nowInSeconds = 1_000;

function prospectusRuntime(responses: Record<string, unknown>) {
  const requests: ProspectusRequest[] = [];
  const runtime: ProspectusSignInRuntime = {
    accounts: new ProspectusSiteAccounts(async (request) => {
      requests.push(request);
      const response = responses[`${request.method} ${request.path}`];
      if (response instanceof Error) throw response;
      if (response === undefined) throw new Error(`unexpected ${request.method} ${request.path}`);
      return response;
    }),
    cognitoClient,
    sealingSecret,
  };
  return { runtime, requests };
}

function routeOptions(runtime: ProspectusSignInRuntime | null, extra: Partial<ProspectusSignInRouteOptions> = {}): ProspectusSignInRouteOptions {
  return { resolveRuntime: async () => runtime, nowInSeconds: () => nowInSeconds, siteProduct: "papyrus-p-apyr-us", environment: { PAPYRUS_SITE_ORIGIN: siteOrigin }, ...extra };
}

function cognitoTokenEndpoint(tokenBody: Record<string, unknown>, status = 200) {
  return (async () => new Response(JSON.stringify(tokenBody), { status })) as unknown as typeof fetch;
}

function browserRequest(path: string, cookies: Record<string, string> = {}, method = "GET"): NextRequest {
  const cookieHeader = Object.entries(cookies).map(([name, value]) => `${name}=${value}`).join("; ");
  return new NextRequest(new URL(path, siteOrigin), { method, headers: cookieHeader ? { cookie: cookieHeader } : {} });
}

function selectionRequest(cookies: Record<string, string>, body: unknown, origin: string | null = siteOrigin): NextRequest {
  const cookieHeader = Object.entries(cookies).map(([name, value]) => `${name}=${value}`).join("; ");
  return new NextRequest(new URL("/api/auth/prospectus/selection", siteOrigin), {
    method: "POST",
    headers: { cookie: cookieHeader, "content-type": "application/json", ...(origin ? { origin } : {}) },
    body: JSON.stringify(body),
  });
}

function setCookie(response: Response, cookieName: string): string | undefined {
  return response.headers.getSetCookie().find((header) => header.startsWith(`${cookieName}=`));
}

function cookieValue(setCookieHeader: string | undefined): string {
  return decodeURIComponent((setCookieHeader ?? "").split(";")[0].split("=").slice(1).join("="));
}

function assertCleared(response: Response, cookieName: string, label: string) {
  const header = setCookie(response, cookieName);
  assert.ok(header, `${label}: ${cookieName} is cleared`);
  assert.match(header!, /Max-Age=0/, `${label}: cleared immediately`);
  assert.match(header!, /Secure/, `${label}: __Host- cookies are cleared with Secure`);
  assert.match(header!, /Path=\//, `${label}: __Host- cookies are cleared at Path=/`);
}

/** A failed sign-in answers 303 to a clean site page with `sign_in_error`, never JSON on /api. */
function assertFailureRedirect(response: Response, path: string, code: string, label = code) {
  assert.equal(response.status, 303, `${label}: a redirect, not an /api error`);
  const location = new URL(response.headers.get("location")!);
  assert.equal(location.origin, siteOrigin, `${label}: stays on the site`);
  assert.equal(location.pathname, path, label);
  assert.equal(location.searchParams.get("sign_in_error"), code, label);
  assert.ok(!location.pathname.startsWith("/api"), `${label}: never ends on /api`);
  assert.equal(setCookie(response, PROSPECTUS_SESSION_COOKIE), undefined, `${label}: no session`);
}

function sealedCookieTests() {
  const sealed = sealProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, { personId: "person-1" }, 2_000);
  assert.deepEqual(openProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, sealed, nowInSeconds), { personId: "person-1" });
  assert.equal(openProspectusCookie(sealingSecret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, sealed, nowInSeconds), null, "a session cookie never opens as a pending sign-in");
  assert.equal(openProspectusCookie(`${sealingSecret}-other`, PROSPECTUS_SESSION_COOKIE, sealed, nowInSeconds), null, "another site's secret cannot open it");
  assert.equal(openProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, sealed, 2_000), null, "expired cookies do not open");
  const tampered = `${sealed.slice(0, -4)}${sealed.slice(-4) === "AAAA" ? "BBBB" : "AAAA"}`;
  assert.equal(openProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, tampered, nowInSeconds), null, "tampered cookies do not open");
  assert.equal(openProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, "garbage", nowInSeconds), null);
  assert.equal(openProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, undefined, nowInSeconds), null);
  assert.throws(() => sealProspectusCookie("short", PROSPECTUS_SESSION_COOKIE, {}, 2_000), /too short/);
}

function returnPathTests() {
  assert.equal(sameSiteReturnPath("/newsroom/board?view=week#top"), "/newsroom/board?view=week#top");
  for (const offSite of [null, "", "https://evil.example/", "//evil.example/", "/\\evil.example", "newsroom", "/\tnewsroom"]) {
    assert.equal(sameSiteReturnPath(offSite), "/", `off-site return path ${JSON.stringify(offSite)} falls back to /`);
  }
}

async function configurationTests() {
  assert.equal(regionOfProspectusAccountsEndpoint("https://abc123defg.execute-api.us-east-1.amazonaws.com/api/"), "us-east-1");
  assert.throws(() => regionOfProspectusAccountsEndpoint("https://example.com/api/"), /execute-api/);
  assert.deepEqual(cognitoClient, {
    hostedUiOrigin: "https://papyrus-p-apyr-us.auth.us-east-1.amazoncognito.com",
    userPoolId: "us-east-1_Synthetic",
    clientId: "googleonlyclient",
    redirectUri: "https://p.apyr.us/api/auth/prospectus/callback",
  });
  assert.equal(googleOnlyCognitoClientFromOutputs({ ...amplifyOutputs, custom: { prospectusSignIn: null } }, siteOrigin), null, "no client output means no sign-in");
  assert.equal(googleOnlyCognitoClientFromOutputs({ custom: amplifyOutputs.custom }, siteOrigin), null, "no hosted UI means no sign-in");

  const configuredEnvironment = {
    PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/",
    PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER: "/papyrus/p-apyr-us/prospectus-session-sealing",
  };
  const readSecret = async () => sealingSecret;
  const unusedTransport = async () => ({});
  resetProspectusSessionSecretCache();
  assert.ok(await resolveProspectusSignInRuntime(siteOrigin, { environment: configuredEnvironment, amplifyOutputs, readSecret, transport: unusedTransport }));
  for (const missing of ["PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT", "PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER"] as const) {
    resetProspectusSessionSecretCache();
    const environment = { ...configuredEnvironment, [missing]: "" };
    assert.equal(await resolveProspectusSignInRuntime(siteOrigin, { environment, amplifyOutputs, readSecret, transport: unusedTransport }), null, `${missing} unset means no sign-in`);
  }
  resetProspectusSessionSecretCache();
  assert.equal(await loadProspectusSessionSealingSecret({ environment: configuredEnvironment, readSecret: async () => "too-short" }), null, "a short secret is refused");
  resetProspectusSessionSecretCache();
  assert.equal(
    await loadProspectusSessionSealingSecret({ environment: configuredEnvironment, readSecret: async () => { throw new Error("AccessDenied"); } }),
    null,
    "an unreadable secret means no sign-in",
  );
  resetProspectusSessionSecretCache();

  const sentCommands: Array<{ Name?: string; WithDecryption?: boolean }> = [];
  const fakeSsm = { send: async (command: { input: { Name?: string; WithDecryption?: boolean } }) => {
    sentCommands.push(command.input);
    return { Parameter: { Value: `  ${sealingSecret}\n` } };
  } };
  assert.equal(await readSealingSecretFromSsm("/papyrus/p-apyr-us/prospectus-session-sealing", fakeSsm as never), sealingSecret, "the SSM reader trims the value");
  assert.deepEqual(sentCommands, [{ Name: "/papyrus/p-apyr-us/prospectus-session-sealing", WithDecryption: true }], "the SSM reader asks for the named parameter, decrypted");

  let reads = 0;
  const countingRead = async () => { reads += 1; return sealingSecret; };
  assert.equal(await loadProspectusSessionSealingSecret({ environment: configuredEnvironment, readSecret: countingRead, now: 1_000 }), sealingSecret);
  assert.equal(await loadProspectusSessionSealingSecret({ environment: configuredEnvironment, readSecret: countingRead, now: 2_000 }), sealingSecret);
  assert.equal(reads, 1, "the container reads the parameter once while the cache is fresh");
  resetProspectusSessionSecretCache();
}

async function signInRouteTests() {
  const unconfiguredStart = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in"), routeOptions(null));
  assert.equal(unconfiguredStart.status, 503);
  assert.equal(setCookie(unconfiguredStart, PROSPECTUS_PENDING_SIGN_IN_COOKIE), undefined, "an unconfigured site starts nothing");

  const person = { id: "person-1", createdAt: "2026-10-17T00:00:00Z" };
  const { runtime, requests } = prospectusRuntime({
    "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300 },
    "POST /v1/identities/google/resolve": { person },
    "GET /v1/account-directory": {
      person,
      accounts: [
        { id: "account-1", name: "Anthus", role: "owner", products: [{ product: "cyclotron", status: "active" }, { product: "papyrus-p-apyr-us", status: "active" }] },
      ],
    },
  });

  const start = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in?returnTo=%2Fnewsroom%2Fboard"), routeOptions(runtime));
  assert.equal(start.status, 303);
  const authorization = new URL(start.headers.get("location")!);
  assert.equal(`${authorization.origin}${authorization.pathname}`, `${cognitoClient.hostedUiOrigin}/oauth2/authorize`);
  assert.equal(authorization.searchParams.get("identity_provider"), "Google");
  assert.equal(authorization.searchParams.get("nonce"), "prospectus-nonce");
  assert.equal(authorization.searchParams.get("redirect_uri"), "https://p.apyr.us/api/auth/prospectus/callback");
  // The reader plugin's "Sign in" button POSTs the return path, so people are never sent to an /api URL.
  const posted = await handleProspectusSignInStart(
    new NextRequest(new URL("/api/auth/prospectus/sign-in", siteOrigin), { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "returnTo=%2Fsign-in%2F" }),
    routeOptions(runtime),
  );
  assert.equal(posted.status, 303);
  assert.equal(new URL(posted.headers.get("location")!).pathname, "/oauth2/authorize");
  const postedPending = openProspectusCookie<{ returnPath: string }>(sealingSecret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, cookieValue(setCookie(posted, PROSPECTUS_PENDING_SIGN_IN_COOKIE)), nowInSeconds);
  assert.equal(postedPending?.returnPath, "/sign-in/", "the POST body names where to come back to");
  const hostile = await handleProspectusSignInStart(
    new NextRequest(new URL("/api/auth/prospectus/sign-in", siteOrigin), { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "returnTo=https%3A%2F%2Fevil.example%2F" }),
    routeOptions(runtime),
  );
  assert.equal(openProspectusCookie<{ returnPath: string }>(sealingSecret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, cookieValue(setCookie(hostile, PROSPECTUS_PENDING_SIGN_IN_COOKIE)), nowInSeconds)?.returnPath, "/", "an off-site return path is dropped");
  const pendingHeader = setCookie(start, PROSPECTUS_PENDING_SIGN_IN_COOKIE);
  assert.ok(pendingHeader, "start seals the pending sign-in into a cookie");
  for (const attribute of [/HttpOnly/, /Secure/, /SameSite=lax/i, /Path=\//, /Max-Age=300/]) assert.match(pendingHeader!, attribute);
  const pendingCookie = cookieValue(pendingHeader);
  assert.equal(pendingCookie.includes("prospectus-nonce"), false, "the pending cookie is sealed, not readable");
  const state = authorization.searchParams.get("state")!;

  const tokenBody = { access_token: "access-jwt", id_token: "id-jwt", refresh_token: "refresh-jwt", expires_in: 3600 };
  const verifiedNonces: string[] = [];
  const completionOverrides = {
    fetcher: cognitoTokenEndpoint(tokenBody),
    verifyCognitoTokens: async (_tokens: unknown, expectedNonce: string) => { verifiedNonces.push(expectedNonce); },
  };

  const forged = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=code-1&state=forged`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pendingCookie }),
    routeOptions(runtime, { completionOverrides }),
  );
  assertFailureRedirect(forged, "/newsroom/board", "state_mismatch");
  assert.equal(setCookie(forged, PROSPECTUS_SESSION_COOKIE), undefined, "a forged state signs no one in");
  assertCleared(forged, PROSPECTUS_PENDING_SIGN_IN_COOKIE, "forged callback");

  const withoutPending = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=code-1&state=${state}`),
    routeOptions(runtime, { completionOverrides }),
  );
  assertFailureRedirect(withoutPending, "/", "sign_in_expired", "a callback in another browser is refused, and lands on the home page");

  const lateCallback = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=code-1&state=${state}`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pendingCookie }),
    routeOptions(runtime, { completionOverrides, nowInSeconds: () => 1_300 }),
  );
  assertFailureRedirect(lateCallback, "/", "sign_in_expired", "a callback after the challenge expires is refused");

  const declined = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?error=access_denied&state=${state}`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pendingCookie }),
    routeOptions(runtime, { completionOverrides }),
  );
  assertFailureRedirect(declined, "/newsroom/board", "sign_in_declined");

  const callback = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=code-1&state=${state}`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pendingCookie }),
    routeOptions(runtime, { completionOverrides }),
  );
  assert.equal(callback.status, 303);
  assert.equal(callback.headers.get("location"), "https://p.apyr.us/newsroom/board", "the person lands where they started");
  assert.deepEqual(verifiedNonces, ["prospectus-nonce"], "tokens are verified against the challenge nonce");
  const resolve = requests.find((request) => request.path === "/v1/identities/google/resolve")!;
  assert.deepEqual(resolve.body, { challengeId: "challenge-1" });
  assertCleared(callback, PROSPECTUS_PENDING_SIGN_IN_COOKIE, "completed callback");
  const sessionHeader = setCookie(callback, PROSPECTUS_SESSION_COOKIE);
  assert.ok(sessionHeader);
  for (const attribute of [/HttpOnly/, /Secure/, /SameSite=lax/i, /Path=\//, /Max-Age=3600/]) assert.match(sessionHeader!, attribute);
  const sessionCookie = cookieValue(sessionHeader);
  for (const secret of ["access-jwt", "id-jwt", "refresh-jwt"]) assert.equal(sessionCookie.includes(secret), false, `${secret} is not readable in the cookie`);
  assert.deepEqual(openProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, sessionCookie, nowInSeconds), {
    personId: "person-1",
    accessToken: "access-jwt",
    accessTokenExpiresAt: 4_600,
  }, "only the access token is kept; the identity and refresh tokens are discarded");

  const signedOutRead = await handleProspectusSessionRead(browserRequest("/api/auth/prospectus/session"), routeOptions(runtime));
  assert.deepEqual(await signedOutRead.json(), { signedIn: false });

  const sessionRead = await handleProspectusSessionRead(
    browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }),
    routeOptions(runtime),
  );
  assert.equal(sessionRead.headers.get("cache-control"), "no-store");
  const sessionBody = await sessionRead.json();
  assert.equal(sessionBody.signedIn, true);
  assert.deepEqual(Object.keys(sessionBody).sort(), ["cyclotronLabAccess", "publishingAccounts", "selectedAccountId", "signedIn"], "the browser gets only what the UI reads");
  assert.equal(JSON.stringify(sessionBody).includes("person-1"), false, "no person id reaches the browser");
  assert.equal(JSON.stringify(sessionBody).includes("createdAt"), false, "no person record reaches the browser");
  assert.equal(sessionBody.cyclotronLabAccess, true, "Cyclotron Lab access comes from an active cyclotron product on one of the person's accounts");
  assert.equal(requests.at(-1)?.humanAccessToken, "access-jwt");
  assert.deepEqual(sessionBody.publishingAccounts, [
    { accountId: "account-1", accountName: "Anthus", role: "owner", publicationCapabilities: ["read", "review", "decide", "steer"] },
  ], "an account with this site's product gets its role's publication capabilities");

  const unregisteredSite = await handleProspectusSessionRead(
    browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }),
    routeOptions(runtime, { siteProduct: null }),
  );
  assert.deepEqual((await unregisteredSite.json()).publishingAccounts, [], "without a site product nobody gets publication access");

  const { runtime: otherPersonRuntime } = prospectusRuntime({ "GET /v1/account-directory": { person: { id: "person-2", createdAt: "" }, accounts: [] } });
  const mismatched = await handleProspectusSessionRead(
    browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }),
    routeOptions(otherPersonRuntime),
  );
  assert.deepEqual(await mismatched.json(), { signedIn: false }, "a session Prospectus maps to someone else is dropped");
  assertCleared(mismatched, PROSPECTUS_SESSION_COOKIE, "mismatched session");

  const { runtime: revokedRuntime } = prospectusRuntime({ "GET /v1/account-directory": new ProspectusAccountsError(401, "invalid_session", "expired") });
  const revoked = await handleProspectusSessionRead(
    browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }),
    routeOptions(revokedRuntime),
  );
  assert.deepEqual(await revoked.json(), { signedIn: false });
  assertCleared(revoked, PROSPECTUS_SESSION_COOKIE, "revoked session");

  const { runtime: noCyclotronRuntime } = prospectusRuntime({
    "GET /v1/account-directory": { person, accounts: [{ id: "account-2", name: "Reader", role: "member", products: [{ product: "cyclotron", status: "disabled" }] }] },
  });
  const noLab = await handleProspectusSessionRead(
    browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }),
    routeOptions(noCyclotronRuntime),
  );
  assert.equal((await noLab.json()).cyclotronLabAccess, false, "a disabled cyclotron product grants no Lab access");

  await accountSelectionTests(sessionCookie, person);
  await publishingAccountCreationTests(sessionCookie, person);

  const signOut = await handleProspectusSignOut(browserRequest("/api/auth/prospectus/sign-out", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }, "POST"), routeOptions(runtime));
  assert.equal(signOut.status, 303);
  const logout = new URL(signOut.headers.get("location")!);
  assert.equal(`${logout.origin}${logout.pathname}`, `${cognitoClient.hostedUiOrigin}/logout`);
  assert.equal(logout.searchParams.get("client_id"), "googleonlyclient");
  assert.equal(logout.searchParams.get("logout_uri"), "https://p.apyr.us/");
  assertCleared(signOut, PROSPECTUS_SESSION_COOKIE, "sign-out");
}

function creationRequest(cookies: Record<string, string>, body: unknown, origin: string | null = siteOrigin): NextRequest {
  const cookieHeader = Object.entries(cookies).map(([name, value]) => `${name}=${value}`).join("; ");
  return new NextRequest(new URL("/api/auth/prospectus/accounts", siteOrigin), {
    method: "POST",
    headers: { cookie: cookieHeader, "content-type": "application/json", ...(origin ? { origin } : {}) },
    body: JSON.stringify(body),
  });
}

async function publishingAccountCreationTests(sessionCookie: string, person: { id: string; createdAt: string }) {
  const createdDirectory = {
    person,
    accounts: [{ id: "new-account", name: "Papyrus", role: "owner", products: [{ product: "papyrus-p-apyr-us", status: "active" }] }],
  };
  const requests: ProspectusRequest[] = [];
  const runtime: ProspectusSignInRuntime = {
    accounts: new ProspectusSiteAccounts(async (request) => {
      requests.push(request);
      if (request.method === "GET" && request.path === "/v1/account-directory") return createdDirectory;
      if (request.path === "/v1/identities/me") return { person };
      if (request.method === "POST" && request.path === "/v1/accounts") return { account: { id: "new-account", name: "Papyrus", role: "owner" } };
      if (request.path === "/v1/accounts/new-account/authorize") {
        return { allowed: true, accountId: "new-account", personId: person.id, product: "papyrus-p-apyr-us", role: "owner", operation: "console:read", revision: 1 };
      }
      throw new Error(`unexpected ${request.method} ${request.path}`);
    }),
    cognitoClient,
    sealingSecret,
  };
  const options = routeOptions(runtime);
  const cookies = { [PROSPECTUS_SESSION_COOKIE]: sessionCookie };
  const idempotencyKey = "0b9c2f4e-6d1a-4c58-9a3b-7e5d8f1a2c40";

  assert.equal((await handleProspectusPublishingAccountCreation(creationRequest(cookies, { name: "Papyrus", idempotencyKey }, "https://evil.example"), options)).status, 403, "another origin cannot create accounts");
  assert.equal((await handleProspectusPublishingAccountCreation(creationRequest({}, { name: "Papyrus", idempotencyKey }), options)).status, 401);
  assert.equal((await handleProspectusPublishingAccountCreation(creationRequest(cookies, { name: "Papyrus" }), options)).status, 400, "an idempotency key is required");
  assert.equal((await handleProspectusPublishingAccountCreation(creationRequest(cookies, { name: "Papyrus", idempotencyKey: "not-a-uuid" }), options)).status, 400);
  assert.equal((await handleProspectusPublishingAccountCreation(creationRequest(cookies, { name: "x".repeat(151), idempotencyKey }), options)).status, 400);
  assert.equal(requests.length, 0, "invalid requests never reach Prospectus");

  const created = await handleProspectusPublishingAccountCreation(creationRequest(cookies, { name: " Papyrus ", idempotencyKey }), options);
  assert.equal(created.status, 201);
  assert.deepEqual(await created.json(), { selectedAccountId: "new-account", role: "owner", publicationCapabilities: ["read", "review", "decide", "steer"] });
  const creationCall = requests.find((request) => request.method === "POST" && request.path === "/v1/accounts")!;
  assert.deepEqual(creationCall.body, { name: "Papyrus" });
  assert.equal(creationCall.idempotencyKey, idempotencyKey, "the caller's key reaches Prospectus so retries are idempotent");
  const createdCookie = cookieValue(setCookie(created, PROSPECTUS_SESSION_COOKIE));
  assert.equal(openProspectusCookie<{ selectedAccountId: string }>(sealingSecret, PROSPECTUS_SESSION_COOKIE, createdCookie, nowInSeconds)?.selectedAccountId, "new-account", "the new account is selected");

  await handleProspectusPublishingAccountCreation(creationRequest(cookies, { idempotencyKey }), options);
  const unnamedCall = requests.filter((request) => request.method === "POST" && request.path === "/v1/accounts").at(-1)!;
  assert.deepEqual(unnamedCall.body, { name: "Publishing account" }, "an omitted name gets the default");
}

async function accountSelectionTests(sessionCookie: string, person: { id: string; createdAt: string }) {
  const directory = {
    person,
    accounts: [
      { id: "account-1", name: "Anthus", role: "member", products: [{ product: "papyrus-p-apyr-us", status: "active" }] },
      { id: "lab-only", name: "Lab", role: "owner", products: [{ product: "cyclotron", status: "active" }] },
    ],
  };
  const authorization = { allowed: true, accountId: "account-1", personId: "person-1", product: "papyrus-p-apyr-us", role: "member", operation: "console:read", revision: 3 };
  const { runtime, requests } = prospectusRuntime({
    "GET /v1/account-directory": directory,
    "GET /v1/identities/me": { person },
    "POST /v1/accounts/account-1/authorize": authorization,
  });
  const options = routeOptions(runtime);

  const crossOrigin = await handleProspectusAccountSelection(selectionRequest({ [PROSPECTUS_SESSION_COOKIE]: sessionCookie }, { accountId: "account-1" }, "https://evil.example"), options);
  assert.equal(crossOrigin.status, 403, "another origin cannot change the selection");
  const noOrigin = await handleProspectusAccountSelection(selectionRequest({ [PROSPECTUS_SESSION_COOKIE]: sessionCookie }, { accountId: "account-1" }, null), options);
  assert.equal(noOrigin.status, 403, "a selection without an origin is refused");
  const signedOut = await handleProspectusAccountSelection(selectionRequest({}, { accountId: "account-1" }), options);
  assert.equal(signedOut.status, 401);
  const missingAccount = await handleProspectusAccountSelection(selectionRequest({ [PROSPECTUS_SESSION_COOKIE]: sessionCookie }, {}), options);
  assert.equal(missingAccount.status, 400);
  const notPublishing = await handleProspectusAccountSelection(selectionRequest({ [PROSPECTUS_SESSION_COOKIE]: sessionCookie }, { accountId: "lab-only" }), options);
  assert.equal(notPublishing.status, 403, "an account without this site's product cannot be selected");
  assert.equal(setCookie(notPublishing, PROSPECTUS_SESSION_COOKIE), undefined);

  const selected = await handleProspectusAccountSelection(selectionRequest({ [PROSPECTUS_SESSION_COOKIE]: sessionCookie }, { accountId: "account-1" }), options);
  assert.equal(selected.status, 200);
  assert.deepEqual(await selected.json(), { selectedAccountId: "account-1", role: "member", publicationCapabilities: ["read", "review", "decide"] });
  assert.deepEqual(requests.find((request) => request.path === "/v1/accounts/account-1/authorize")?.body, { operation: "console:read" }, "selection is authorized fresh by Prospectus");
  const selectedHeader = setCookie(selected, PROSPECTUS_SESSION_COOKIE);
  assert.match(selectedHeader!, /Max-Age=3600/, "selection keeps the session's original expiry");
  const selectedCookie = cookieValue(selectedHeader);
  assert.equal(openProspectusCookie<{ selectedAccountId: string }>(sealingSecret, PROSPECTUS_SESSION_COOKIE, selectedCookie, nowInSeconds)?.selectedAccountId, "account-1");

  const sessionWithSelection = await handleProspectusSessionRead(browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: selectedCookie }), options);
  assert.equal((await sessionWithSelection.json()).selectedAccountId, "account-1");

  assert.deepEqual(
    await currentProspectusPublishingSelection(browserRequest("/api/newsroom/curation", { [PROSPECTUS_SESSION_COOKIE]: selectedCookie }), options),
    { personId: "person-1", accountId: "account-1", role: "member", publicationCapabilities: ["read", "review", "decide"] },
    "server code gets the selection with capabilities from a fresh authorization",
  );
  assert.equal(await currentProspectusPublishingSelection(browserRequest("/api/newsroom/curation", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }), options), null, "no selection until one is chosen");

  const { runtime: removedRuntime } = prospectusRuntime({
    "GET /v1/account-directory": { person, accounts: [] },
  });
  const removedOptions = routeOptions(removedRuntime);
  assert.equal(
    await currentProspectusPublishingSelection(browserRequest("/api/newsroom/curation", { [PROSPECTUS_SESSION_COOKIE]: selectedCookie }), removedOptions),
    null,
    "a person removed from the account loses the selection immediately",
  );
  assert.equal((await (await handleProspectusSessionRead(browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: selectedCookie }), removedOptions)).json()).selectedAccountId, null);

  const { runtime: deniedRuntime } = prospectusRuntime({
    "GET /v1/account-directory": directory,
    "GET /v1/identities/me": { person },
    "POST /v1/accounts/account-1/authorize": new ProspectusAccountsError(403, "forbidden", "no"),
  });
  assert.equal(
    await currentProspectusPublishingSelection(browserRequest("/api/newsroom/curation", { [PROSPECTUS_SESSION_COOKIE]: selectedCookie }), routeOptions(deniedRuntime)),
    null,
    "a Prospectus refusal clears access",
  );
}

function publicationAccessTests() {
  assert.deepEqual(publicationCapabilitiesForProspectusRole("viewer"), ["read"]);
  assert.deepEqual(publicationCapabilitiesForProspectusRole("member"), ["read", "review", "decide"]);
  assert.deepEqual(publicationCapabilitiesForProspectusRole("admin"), ["read", "review", "decide", "steer"]);
  assert.deepEqual(publicationCapabilitiesForProspectusRole("owner"), ["read", "review", "decide", "steer"]);
  assert.deepEqual(publicationCapabilitiesForProspectusRole("guest"), []);
  assert.equal(prospectusSiteProduct({ PAPYRUS_PROSPECTUS_SITE_PRODUCT: "papyrus-p-apyr-us" }), "papyrus-p-apyr-us");
  assert.equal(prospectusSiteProduct({ PAPYRUS_PROSPECTUS_SITE_PRODUCT: "cyclotron" }), null, "only papyrus- products name a site");
  assert.equal(prospectusSiteProduct({}), null);
  const accounts = [
    { id: "publisher", name: "Publisher", role: "member" as const, products: [{ product: "papyrus-p-apyr-us", status: "active" as const }] },
    { id: "lapsed", name: "Lapsed", role: "owner" as const, products: [{ product: "papyrus-p-apyr-us", status: "disabled" as const }] },
    { id: "other-site", name: "Other", role: "owner" as const, products: [{ product: "papyrus-pilobol-us", status: "active" as const }] },
    { id: "lab-only", name: "Lab", role: "admin" as const, products: [{ product: "cyclotron", status: "active" as const }] },
  ];
  assert.deepEqual(publishingAccountsForSite(accounts, "papyrus-p-apyr-us"), [
    { accountId: "publisher", accountName: "Publisher", role: "member", publicationCapabilities: ["read", "review", "decide"] },
  ], "only accounts with this site's active product publish here");
}

function googleOnlyClientTests() {
  const redirectUrls = ["http://localhost:3000/", "https://p.apyr.us/", "https://p.apyr.us/newsroom", "not a url"];
  assert.deepEqual(prospectusSignInCallbackUrls(redirectUrls), [
    "http://localhost:3000/api/auth/prospectus/callback",
    "https://p.apyr.us/api/auth/prospectus/callback",
  ]);
  assert.deepEqual(prospectusSignInLogoutUrls(redirectUrls), ["http://localhost:3000/", "https://p.apyr.us/"]);

  const app = new App();
  const authStack = new Stack(app, "Auth", { env: { account: "111111111111", region: "us-east-1" } });
  const userPool = new UserPool(authStack, "UserPool");
  new UserPoolIdentityProviderGoogle(authStack, "Google", { userPool, clientId: "google-client", clientSecretValue: SecretValue.unsafePlainText("google-secret") });
  addProspectusGoogleOnlyClient(authStack, userPool, redirectUrls);
  const template = Template.fromStack(authStack);
  const clients = template.findResources("AWS::Cognito::UserPoolClient");
  const [clientKey, client] = Object.entries(clients)[0];
  assert.equal(Object.keys(clients).length, 1);
  assert.deepEqual(client.Properties.SupportedIdentityProviders, ["Google"], "Google is the only provider");
  assert.deepEqual(client.Properties.AllowedOAuthFlows, ["code"], "code flow only");
  assert.deepEqual(client.Properties.ExplicitAuthFlows, ["ALLOW_REFRESH_TOKEN_AUTH"], "no password, SRP or custom auth");
  assert.equal(client.Properties.GenerateSecret, false);
  assert.equal(client.Properties.EnableTokenRevocation, true);
  assert.deepEqual(client.Properties.CallbackURLs, prospectusSignInCallbackUrls(redirectUrls));
  const googleProviderKey = Object.keys(template.findResources("AWS::Cognito::UserPoolIdentityProvider"))[0];
  assert.ok(client.DependsOn?.includes(googleProviderKey), "the client waits for the Google provider");
  assert.deepEqual(template.toJSON().Outputs.ProspectusGoogleOnlyClientId.Value, { Ref: clientKey });
  assert.ok(template.toJSON().Outputs.ProspectusGoogleOnlyIssuer, "the issuer is published for registration");
  assert.throws(() => addProspectusGoogleOnlyClient(new Stack(app, "Empty"), userPool, ["not a url"]), /at least one site origin/);
}

// Amplify SSR WEB_COMPUTE: the request URL is the compute adapter's internal origin, never the public host.
const computeAdapterOrigin = "https://localhost:3000";

function computeRequest(path: string, method = "GET", headers: Record<string, string> = {}, body?: unknown): NextRequest {
  return new NextRequest(new URL(path, computeAdapterOrigin), { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}

async function publicSiteOriginTests() {
  const environment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };
  const { runtime } = prospectusRuntime({ "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300 } });
  let resolvedFor: string | null = null;
  const resolveRuntime = async (origin: string) => { resolvedFor = origin; return runtime; };

  const start = await handleProspectusSignInStart(computeRequest("/api/auth/prospectus/sign-in"), { ...routeOptions(runtime), resolveRuntime, environment });
  assert.equal(start.status, 303);
  assert.equal(resolvedFor, siteOrigin, "behind the compute adapter the runtime resolves for the public origin");
  assert.equal(new URL(start.headers.get("location")!).searchParams.get("redirect_uri"), "https://p.apyr.us/api/auth/prospectus/callback", "the redirect_uri is public, not localhost");

  const signOut = await handleProspectusSignOut(computeRequest("/api/auth/prospectus/sign-out", "POST"), { ...routeOptions(null), environment });
  assert.equal(signOut.headers.get("location"), "https://p.apyr.us/", "signed-out redirect is public when sign-in is unavailable");
  const signedOut = await handleProspectusSignOut(computeRequest("/api/auth/prospectus/sign-out", "POST"), { ...routeOptions(runtime), environment });
  assert.equal(new URL(signedOut.headers.get("location")!).searchParams.get("logout_uri"), "https://p.apyr.us/", "logout_uri is public");

  const body = { accountId: "account-1" };
  const withOrigin = (origin: string) => computeRequest("/api/auth/prospectus/selection", "POST", { "content-type": "application/json", origin }, body);
  assert.equal((await handleProspectusAccountSelection(withOrigin(siteOrigin), { ...routeOptions(runtime), environment })).status, 401, "the public Origin passes the same-origin check (then needs a session)");
  for (const rejected of [computeAdapterOrigin, "https://evil.example", "http://p.apyr.us"]) {
    assert.equal((await handleProspectusAccountSelection(withOrigin(rejected), { ...routeOptions(runtime), environment })).status, 403, `selection rejects Origin ${rejected}`);
    const creation = computeRequest("/api/auth/prospectus/accounts", "POST", { "content-type": "application/json", origin: rejected }, { name: "x" });
    assert.equal((await handleProspectusPublishingAccountCreation(creation, { ...routeOptions(runtime), environment })).status, 403, `creation rejects Origin ${rejected}`);
  }
  const creation = computeRequest("/api/auth/prospectus/accounts", "POST", { "content-type": "application/json", origin: siteOrigin }, { name: "x" });
  assert.equal((await handleProspectusPublishingAccountCreation(creation, { ...routeOptions(runtime), environment })).status, 401, "creation accepts the public Origin");
}

async function consoleOriginTests() {
  const consoleOrigin = "https://newsroom.p.apyr.us";
  const { runtime } = prospectusRuntime({});
  const post = (path: string, origin: string, body: unknown) => computeRequest(path, "POST", { "content-type": "application/json", origin }, body);
  const withConsole = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production", PAPYRUS_CONSOLE_ORIGIN: consoleOrigin };
  const without = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };
  const routes: Array<[string, (request: NextRequest, options: ProspectusSignInRouteOptions) => Promise<{ status: number }>, unknown]> = [
    ["/api/auth/prospectus/selection", handleProspectusAccountSelection, { accountId: "account-1" }],
    ["/api/auth/prospectus/accounts", handleProspectusPublishingAccountCreation, { name: "x" }],
  ];
  for (const [path, handler, body] of routes) {
    assert.equal((await handler(post(path, consoleOrigin, body), { ...routeOptions(runtime), environment: withConsole })).status, 401, `${path} accepts the console Origin when configured`);
    assert.equal((await handler(post(path, "https://evil.example", body), { ...routeOptions(runtime), environment: withConsole })).status, 403, `${path} still refuses a foreign Origin`);
    assert.equal((await handler(post(path, consoleOrigin, body), { ...routeOptions(runtime), environment: without })).status, 403, `${path} refuses the console Origin when none is configured`);
  }
  const connect = (origin: string, environment: Record<string, string>) => handleProspectusSignInStart(
    computeRequest("/api/auth/prospectus/sign-in?newsroomChat=true", "POST", { origin }), { ...routeOptions(runtime), environment });
  assert.equal((await connect(consoleOrigin, withConsole)).status, 401, "newsroom chat connect accepts the console Origin (then needs a newsroom identity)");
  assert.equal((await connect(consoleOrigin, without)).status, 403, "newsroom chat connect refuses the console Origin when none is configured");
  assert.equal((await connect("https://evil.example", withConsole)).status, 403, "newsroom chat connect refuses a foreign Origin");
}

async function siteOriginFailsClosedTests() {
  const { runtime } = prospectusRuntime({ "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300 } });
  for (const environment of [{ SITE_ENV: "production" }, { SITE_ENV: "staging" }, { PAPYRUS_SITE_ORIGIN: "http://p.apyr.us" }, { PAPYRUS_SITE_ORIGIN: "https://p.apyr.us/path" }, { PAPYRUS_SITE_ORIGIN: "https://p.apyr.us/" }, { PAPYRUS_SITE_ORIGIN: "p.apyr.us" }]) {
    const options = { ...routeOptions(runtime), environment };
    const label = JSON.stringify(environment);
    const start = await handleProspectusSignInStart(computeRequest("/api/auth/prospectus/sign-in"), options);
    assert.equal(start.status, 503, `${label}: sign-in fails closed`);
    assert.equal(start.headers.get("location"), null, `${label}: never redirects to localhost`);
    assert.equal((await start.json()).error, "site_origin_not_configured");
    assert.equal((await handleProspectusSignOut(computeRequest("/api/auth/prospectus/sign-out", "POST"), options)).status, 503, `${label}: sign-out fails closed`);
    assert.equal((await handleProspectusSessionRead(computeRequest("/api/auth/prospectus/session"), options)).status, 503, `${label}: session read fails closed`);
    const selection = computeRequest("/api/auth/prospectus/selection", "POST", { "content-type": "application/json", origin: computeAdapterOrigin }, {});
    assert.equal((await handleProspectusAccountSelection(selection, options)).status, 503, `${label}: localhost Origin is not accepted`);
  }
  // Host and forwarding headers are never trusted.
  const spoofed = computeRequest("/api/auth/prospectus/sign-in", "GET", { host: "evil.example", "x-forwarded-host": "evil.example", "x-forwarded-proto": "https" });
  assert.equal((await handleProspectusSignInStart(spoofed, { ...routeOptions(runtime), environment: { SITE_ENV: "production" } })).status, 503);
  const configured = await handleProspectusSignInStart(spoofed, { ...routeOptions(runtime), environment: { PAPYRUS_SITE_ORIGIN: siteOrigin } });
  assert.equal(new URL(configured.headers.get("location")!).searchParams.get("redirect_uri"), "https://p.apyr.us/api/auth/prospectus/callback", "forwarded headers do not change the origin");
}

async function loopbackDevelopmentFallbackTests() {
  const { runtime } = prospectusRuntime({ "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300 } });
  let resolvedFor: string | null = null;
  const resolveRuntime = async (origin: string) => { resolvedFor = origin; return runtime; };
  for (const [origin, environment] of [["http://localhost:3001", {}], ["http://127.0.0.1:3001", { SITE_ENV: "development" }], ["http://[::1]:3001", {}]] as const) {
    const start = await handleProspectusSignInStart(new NextRequest(new URL("/api/auth/prospectus/sign-in", origin)), { ...routeOptions(runtime), resolveRuntime, environment });
    assert.equal(start.status, 303, `${origin}: local development still starts sign-in`);
    const requestOrigin = new NextRequest(new URL("/", origin)).nextUrl.origin; // Next normalizes 127.0.0.1 to localhost
    assert.equal(resolvedFor, requestOrigin, "the loopback request origin is used");
    const selection = new NextRequest(new URL("/api/auth/prospectus/selection", origin), { method: "POST", headers: { "content-type": "application/json", origin: requestOrigin }, body: "{}" });
    assert.equal((await handleProspectusAccountSelection(selection, { ...routeOptions(runtime), environment })).status, 401, `${origin}: same-origin check passes locally`);
  }
  const lookalike = new NextRequest(new URL("/api/auth/prospectus/sign-in", "https://localhost.evil.example"));
  assert.equal((await handleProspectusSignInStart(lookalike, { ...routeOptions(runtime), environment: {} })).status, 503, "a non-loopback host never falls back");
}

/** A Prospectus that signs its challenges stores nothing, so the signed token must survive the pending cookie byte for byte and be the only challenge reference resolve receives. */
async function signedChallengeTests() {
  const person = { id: "person-1", createdAt: "2026-10-17T00:00:00Z" };
  const challengeToken = `v1.k1.${"A".repeat(520)}_-.${"B".repeat(43)}`;
  const { runtime, requests } = prospectusRuntime({
    "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300, challengeToken },
    "POST /v1/identities/google/resolve": { person },
  });
  const start = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in"), routeOptions(runtime));
  const authorization = new URL(start.headers.get("location")!);
  assert.equal(authorization.searchParams.get("nonce"), "prospectus-nonce", "the authorize request carries the challenge nonce");
  const pendingCookie = cookieValue(setCookie(start, PROSPECTUS_PENDING_SIGN_IN_COOKIE));
  assert.ok(pendingCookie.length < 3_000, "the sealed pending cookie stays well under the 4 KB cookie limit");
  assert.equal(pendingCookie.includes(challengeToken), false, "the token is sealed in the cookie");
  assert.equal(
    openProspectusCookie<{ challengeToken?: string }>(sealingSecret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, pendingCookie, nowInSeconds)?.challengeToken,
    challengeToken,
    "the token round-trips byte-exact",
  );
  const callback = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=code-1&state=${authorization.searchParams.get("state")}`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pendingCookie }),
    routeOptions(runtime, { completionOverrides: { fetcher: cognitoTokenEndpoint({ access_token: "access-jwt", id_token: "id-jwt", expires_in: 3600 }), verifyCognitoTokens: async () => {} } }),
  );
  assert.equal(callback.status, 303);
  assert.ok(setCookie(callback, PROSPECTUS_SESSION_COOKIE), "the sign-in completes");
  assert.deepEqual(requests.find((request) => request.path === "/v1/identities/google/resolve")!.body, { challengeToken }, "resolve gets the signed token alone, not the unstored ID");

  // Two starts (a reload or prefetch) each seal their own challenge, so the later cookie never carries the earlier token.
  const second = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in"), routeOptions(runtime));
  assert.equal(new URL(second.headers.get("location")!).searchParams.get("nonce"), "prospectus-nonce");
}

/** Every callback failure logs exactly one structured line with the code and branch, and nothing secret. */
async function failureLoggingTests() {
  const person = { id: "person-1", createdAt: "2026-10-17T00:00:00Z" };
  const { runtime } = prospectusRuntime({
    "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300 },
    "POST /v1/identities/google/resolve": { person },
  });
  const start = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in"), routeOptions(runtime));
  const pendingCookie = cookieValue(setCookie(start, PROSPECTUS_PENDING_SIGN_IN_COOKIE));
  const state = new URL(start.headers.get("location")!).searchParams.get("state")!;
  const pending = { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pendingCookie };
  const tokenBody = { access_token: "secret-access-jwt", id_token: "secret-id-jwt", expires_in: 3600 };
  const verifyOk = async () => {};

  async function logged(path: string, cookies: Record<string, string>, extra: Partial<ProspectusSignInRouteOptions>) {
    const lines: string[] = [];
    const response = await handleProspectusSignInCallback(
      browserRequest(path, cookies),
      routeOptions(runtime, { log: (line) => lines.push(line), ...extra }),
    );
    return { response, lines };
  }
  function entryOf(lines: string[]) {
    assert.equal(lines.length, 1, "exactly one line per failure");
    assert.ok(lines[0].startsWith("prospectus_sign_in_failed "), "a greppable event name");
    return JSON.parse(lines[0].slice("prospectus_sign_in_failed ".length)) as Record<string, unknown>;
  }

  const noCookie = await logged(`/api/auth/prospectus/callback?code=secret-code&state=${state}`, {}, {});
  assert.deepEqual(entryOf(noCookie.lines), { code: "sign_in_expired", branch: "pending_cookie" });
  const declined = await logged(`/api/auth/prospectus/callback?error=access_denied&state=${state}`, pending, {});
  assert.deepEqual(entryOf(declined.lines), { code: "sign_in_declined", branch: "provider_error" });
  const incomplete = await logged(`/api/auth/prospectus/callback?state=${state}`, pending, {});
  assert.deepEqual(entryOf(incomplete.lines), { code: "sign_in_incomplete", branch: "missing_parameters" });
  const forged = await logged(`/api/auth/prospectus/callback?code=secret-code&state=forged`, pending, { completionOverrides: { fetcher: cognitoTokenEndpoint(tokenBody), verifyCognitoTokens: verifyOk } });
  assert.deepEqual(entryOf(forged.lines), { code: "state_mismatch", branch: "completion", httpStatus: 401, prospectusError: "state_mismatch", prospectusMessage: "Sign-in response does not belong to this browser's sign-in." });
  const refused = await logged(`/api/auth/prospectus/callback?code=secret-code&state=${state}`, pending, {
    completionOverrides: { fetcher: cognitoTokenEndpoint({ error: "invalid_grant" }, 400), verifyCognitoTokens: verifyOk },
  });
  assert.equal(entryOf(refused.lines).code, "code_exchange_failed");
  const mismatch = await logged(`/api/auth/prospectus/callback?code=secret-code&state=${state}`, pending, {
    completionOverrides: {
      fetcher: cognitoTokenEndpoint(tokenBody),
      verifyCognitoTokens: async () => { throw new ProspectusAccountsError(401, "nonce_mismatch", "Sign-in did not carry this site's Prospectus challenge."); },
    },
  });
  assert.deepEqual(entryOf(mismatch.lines), { code: "nonce_mismatch", branch: "completion", httpStatus: 401, prospectusError: "nonce_mismatch", prospectusMessage: "Sign-in did not carry this site's Prospectus challenge." });
  assertFailureRedirect(mismatch.response, "/", "nonce_mismatch");
  const unexpected = await logged(`/api/auth/prospectus/callback?code=secret-code&state=${state}`, pending, {
    completionOverrides: { fetcher: cognitoTokenEndpoint(tokenBody), verifyCognitoTokens: async () => { throw new TypeError("boom secret-id-jwt"); } },
  });
  assert.deepEqual(entryOf(unexpected.lines), { code: "sign_in_failed", branch: "unexpected", errorName: "TypeError" });

  // A Prospectus refusal is logged with its rule text, so the broken rule is visible without a debugger.
  const { runtime: refusingRuntime } = prospectusRuntime({
    "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "prospectus-nonce", expiresAt: 1_300 },
    "POST /v1/identities/google/resolve": new ProspectusAccountsError(401, "challenge_invalid", "Challenge does not exist."),
  });
  const refusedStart = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in"), routeOptions(refusingRuntime));
  const refusedLines: string[] = [];
  await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=secret-code&state=${new URL(refusedStart.headers.get("location")!).searchParams.get("state")}`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: cookieValue(setCookie(refusedStart, PROSPECTUS_PENDING_SIGN_IN_COOKIE)) }),
    routeOptions(refusingRuntime, { log: (line) => refusedLines.push(line), completionOverrides: { fetcher: cognitoTokenEndpoint(tokenBody), verifyCognitoTokens: verifyOk } }),
  );
  assert.deepEqual(entryOf(refusedLines), { code: "challenge_invalid", branch: "completion", httpStatus: 401, prospectusError: "challenge_invalid", prospectusMessage: "Challenge does not exist." });

  for (const { lines } of [noCookie, declined, incomplete, forged, refused, mismatch, unexpected]) {
    for (const secret of ["secret-code", "secret-access-jwt", "secret-id-jwt", state, pendingCookie, "person-1", "prospectus-nonce"]) {
      assert.equal(lines[0].includes(secret), false, "the log line never carries tokens, codes, state or subjects");
    }
  }
}

async function main() {
  sealedCookieTests();
  returnPathTests();
  await configurationTests();
  await signInRouteTests();
  await publicSiteOriginTests();
  await consoleOriginTests();
  await siteOriginFailsClosedTests();
  await loopbackDevelopmentFallbackTests();
  publicationAccessTests();
  googleOnlyClientTests();
  await signedChallengeTests();
  await failureLoggingTests();
  console.log("prospectus sign-in routes: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
