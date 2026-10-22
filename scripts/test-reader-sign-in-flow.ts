import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import {
  PROSPECTUS_PENDING_SIGN_IN_COOKIE,
  PROSPECTUS_SESSION_COOKIE,
  googleOnlyCognitoClientFromOutputs,
  openProspectusCookie,
  type ProspectusSignInRuntime,
  type ProspectusSignedInSession,
} from "../lib/prospectus-session";
import {
  handleProspectusSessionRead,
  handleProspectusSignInCallback,
  handleProspectusSignInStart,
  type ProspectusSignInRouteOptions,
} from "../lib/prospectus-sign-in-routes";
import { ProspectusAccountsError, ProspectusSiteAccounts, type ProspectusRequest } from "../lib/prospectus-site-identity";
import { handleReaderRequest, type ReaderActionEvent } from "../lib/reader-api";
import { readerSubject } from "../lib/reader-subject";

/**
 * The reader sign-in path end to end, with a stubbed Prospectus transport and no real Google login:
 * start, callback (which seals person.siteSubject into the session), readerSubject, the reader API,
 * and the browser-facing session route.
 */
const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const siteOrigin = "https://reader.example.test";
const siteSubject = `ss1_${"C".repeat(43)}`;
const nowInSeconds = 1_000;
const environment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };
const cognitoClient = googleOnlyCognitoClientFromOutputs(
  {
    auth: { user_pool_id: "us-east-1_Synthetic", oauth: { domain: "reader.auth.us-east-1.amazoncognito.com" } },
    custom: { prospectusSignIn: { clientId: "googleonlyclient", callbackPath: "/api/auth/prospectus/callback" } },
  },
  siteOrigin,
)!;

function runtimeFor(responses: Record<string, unknown>): ProspectusSignInRuntime {
  return {
    accounts: new ProspectusSiteAccounts(async (request: ProspectusRequest) => {
      const response = responses[`${request.method} ${request.path}`];
      if (response instanceof Error) throw response;
      if (response === undefined) throw new Error(`unexpected ${request.method} ${request.path}`);
      return response;
    }),
    cognitoClient,
    sealingSecret,
  };
}

function options(runtime: ProspectusSignInRuntime): ProspectusSignInRouteOptions {
  return {
    resolveRuntime: async () => runtime,
    nowInSeconds: () => nowInSeconds,
    siteProduct: "papyrus-reader-example",
    environment,
    completionOverrides: {
      fetcher: (async () => new Response(JSON.stringify({ access_token: "a.b.c", id_token: "d.e.f", expires_in: 3600 }), { status: 200 })) as unknown as typeof fetch,
      verifyCognitoTokens: async () => {},
    },
  };
}

function browserRequest(path: string, cookies: Record<string, string> = {}): NextRequest {
  const cookie = Object.entries(cookies).map(([name, value]) => `${name}=${value}`).join("; ");
  return new NextRequest(new URL(path, siteOrigin), { headers: cookie ? { cookie } : {} });
}

function cookieOf(response: Response, name: string): string {
  const header = response.headers.getSetCookie().find((candidate) => candidate.startsWith(`${name}=`));
  return decodeURIComponent((header ?? "").split(";")[0].split("=").slice(1).join("="));
}

async function signIn(responses: Record<string, unknown>): Promise<{ response: Response; sessionCookie: string; runtime: ProspectusSignInRuntime }> {
  const runtime = runtimeFor({
    "POST /v1/identities/google/challenge": { challengeId: "challenge-1", nonce: "nonce-1", expiresAt: 1_300 },
    ...responses,
  });
  const start = await handleProspectusSignInStart(browserRequest("/api/auth/prospectus/sign-in"), options(runtime));
  const state = new URL(start.headers.get("location")!).searchParams.get("state")!;
  const pending = cookieOf(start, PROSPECTUS_PENDING_SIGN_IN_COOKIE);
  const response = await handleProspectusSignInCallback(
    browserRequest(`/api/auth/prospectus/callback?code=code-1&state=${state}`, { [PROSPECTUS_PENDING_SIGN_IN_COOKIE]: pending }),
    options(runtime),
  );
  return { response, sessionCookie: cookieOf(response, PROSPECTUS_SESSION_COOKIE), runtime };
}

async function readerMe(sessionCookie: string): Promise<{ status: number; error?: unknown; events: ReaderActionEvent[] }> {
  const events: ReaderActionEvent[] = [];
  const response = await handleReaderRequest(browserRequest("/api/reader/me", { [PROSPECTUS_SESSION_COOKIE]: sessionCookie }), "me", {
    environment,
    nowInSeconds,
    actionsFunctionName: "reader-actions-test",
    loadSealingSecret: async () => sealingSecret,
    invoke: async (_name, event) => {
      events.push(event);
      return { statusCode: 200, body: { readerId: "reader-1", handle: null, karma: 0, state: "active", votes: {} } };
    },
  });
  const body = (await response.json()) as { error?: unknown };
  return { status: response.status, error: body.error, events };
}

(async () => {
  // A public-reader site: Prospectus returns person.siteSubject and no id or createdAt.
  const publicReaderPerson = { siteSubject };
  const withSubject = await signIn({
    "POST /v1/identities/google/resolve": { person: publicReaderPerson },
    "GET /v1/account-directory": { person: publicReaderPerson, accounts: [] },
  });
  assert.equal(withSubject.response.status, 303);
  const session = openProspectusCookie<ProspectusSignedInSession>(sealingSecret, PROSPECTUS_SESSION_COOKIE, withSubject.sessionCookie, nowInSeconds);
  assert.ok(session, "the callback sealed a session");
  assert.equal(session!.siteSubject, siteSubject, "the callback copies person.siteSubject into the sealed session");
  assert.equal(readerSubject(session, environment), siteSubject, "readerSubject yields it in production");
  assert.equal(withSubject.sessionCookie.includes(siteSubject), false, "the cookie is sealed, not readable");

  const open = await readerMe(withSubject.sessionCookie);
  assert.equal(open.status, 200, "the reader API is open");
  assert.equal(open.events.length, 1);
  assert.equal(open.events[0].siteSubject, siteSubject, "the function is invoked with the siteSubject");

  // The browser-facing session route stays usable for a person with no id, and shows no identity.
  const sessionRead = await handleProspectusSessionRead(browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: withSubject.sessionCookie }), options(withSubject.runtime));
  const sessionText = await sessionRead.text();
  assert.equal(JSON.parse(sessionText).signedIn, true);
  assert.deepEqual(Object.keys(JSON.parse(sessionText)).sort(), ["cyclotronLabAccess", "publishingAccounts", "selectedAccountId", "signedIn"]);
  assertNoIdentity(sessionText, "session route (public-reader person)");

  // A person record from a staff site carries a global id; the session route must not forward it either.
  const staffPerson = { id: "person-global-id-123", createdAt: "2026-10-17T00:00:00Z", siteSubject };
  const staff = await signIn({
    "POST /v1/identities/google/resolve": { person: staffPerson },
    "GET /v1/account-directory": {
      person: staffPerson,
      accounts: [{ id: "account-1", name: "Reader Desk", role: "owner", products: [{ product: "papyrus-reader-example", status: "active" }] }],
    },
  });
  const staffRead = await handleProspectusSessionRead(browserRequest("/api/auth/prospectus/session", { [PROSPECTUS_SESSION_COOKIE]: staff.sessionCookie }), options(staff.runtime));
  const staffText = await staffRead.text();
  const staffBody = JSON.parse(staffText);
  assert.equal(staffBody.publishingAccounts.length, 1, "staff console behaviour still works");
  assertNoIdentity(staffText, "session route (staff person)");

  // Prospectus answers without a siteSubject: readerSubject is null and the API says 503.
  const withoutSubject = await signIn({
    "POST /v1/identities/google/resolve": { person: { id: "person-global-id-123", createdAt: "2026-10-17T00:00:00Z" } },
  });
  assert.equal(withoutSubject.response.status, 303, "sign-in itself still works");
  const bare = openProspectusCookie<ProspectusSignedInSession>(sealingSecret, PROSPECTUS_SESSION_COOKIE, withoutSubject.sessionCookie, nowInSeconds)!;
  assert.equal(bare.siteSubject, undefined);
  assert.equal(readerSubject(bare, environment), null, "no siteSubject, no reader subject in production");
  const closed = await readerMe(withoutSubject.sessionCookie);
  assert.equal(closed.status, 503);
  assert.equal(closed.error, "reader_identity_unavailable");
  assert.equal(closed.events.length, 0, "nothing is invoked");

  // Prospectus itself answering 503 (a missing secret on its side) signs no one in.
  const unavailable = await signIn({
    "POST /v1/identities/google/resolve": new ProspectusAccountsError(503, "service_unavailable", "Site subjects are not configured."),
  });
  assert.equal(unavailable.response.status, 303, "the browser goes back to the site, not to an /api error");
  const back = new URL(unavailable.response.headers.get("location")!);
  assert.equal(back.pathname, "/");
  assert.equal(back.searchParams.get("sign_in_error"), "service_unavailable");
  assert.equal(unavailable.sessionCookie, "", "no session is created");

  console.log("reader sign-in flow ok");
})();

function assertNoIdentity(text: string, label: string): void {
  for (const pattern of [/ss(?:1|dev)_[A-Za-z0-9_-]{8,}/, /person[-_ ]?id/i, /\bperson-[A-Za-z0-9-]{6,}/, /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, /createdAt/]) {
    assert.equal(pattern.test(text), false, `${label}: ${pattern} must not appear`);
  }
}
