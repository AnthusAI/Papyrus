import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";
import { handleReaderRequest, type ReaderActionEvent, type ReaderActionResult } from "../lib/reader-api";
import { READER_DEV_SECRET_ENV, readerIsStaff } from "../lib/reader-subject";

const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const siteOrigin = "https://reader.example.test";
const siteSubject = `ss1_${"B".repeat(43)}`;
const personId = "person-global-id-123";
const nowInSeconds = 1_000;
const productionEnvironment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };
const developmentEnvironment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "development", [READER_DEV_SECRET_ENV]: "development-only-secret-0123456789" };

function cookieFor(session: Record<string, unknown> | null): Record<string, string> {
  if (!session) return {};
  return { [PROSPECTUS_SESSION_COOKIE]: sealProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, session, nowInSeconds + 3600) };
}
const signedIn = (changes: Record<string, unknown> = {}) => ({ personId, accessToken: "x.y.z", accessTokenExpiresAt: nowInSeconds + 3600, siteSubject, ...changes });

function request(method: string, path: string, options: { cookies?: Record<string, string>; origin?: string | null; contentType?: string | null; body?: string } = {}): NextRequest {
  const cookie = Object.entries(options.cookies ?? {}).map(([name, value]) => `${name}=${value}`).join("; ");
  const headers: Record<string, string> = {};
  if (cookie) headers.cookie = cookie;
  if (options.origin !== null && method !== "GET") headers.origin = options.origin ?? siteOrigin;
  if (options.contentType !== null && method !== "GET") headers["content-type"] = options.contentType ?? "application/json";
  return new NextRequest(new URL(path, "https://localhost:3000"), { method, headers, ...(options.body === undefined ? {} : { body: options.body }) });
}

function harness(result: ReaderActionResult = { statusCode: 200, body: { ok: true } }) {
  const calls: Array<{ functionName: string; event: ReaderActionEvent }> = [];
  return {
    calls,
    options: {
      environment: productionEnvironment as Record<string, string | undefined>,
      nowInSeconds,
      actionsFunctionName: "reader-actions-test",
      loadSealingSecret: async () => sealingSecret as string | null,
      invoke: async (functionName: string, event: ReaderActionEvent) => {
        calls.push({ functionName, event });
        return result;
      },
    },
  };
}

async function json(response: Response) {
  return { status: response.status, body: (await response.json()) as Record<string, unknown>, headers: response.headers };
}

(async () => {
  // The production switch: a signed-in reader whose session has no siteSubject gets 503 on every route, and nothing is invoked.
  for (const [action, method, path] of [["me", "GET", "/api/reader/me"], ["handle", "POST", "/api/reader/handle"], ["vote", "POST", "/api/reader/vote"], ["rating", "POST", "/api/reader/rating"]] as const) {
    const { calls, options } = harness();
    const answer = await json(await handleReaderRequest(request(method, path, { cookies: cookieFor(signedIn({ siteSubject: undefined })), body: method === "POST" ? "{}" : undefined }), action, options));
    assert.equal(answer.status, 503, `${action} without a siteSubject`);
    assert.equal(answer.body.error, "reader_identity_unavailable");
    assert.equal(answer.headers.get("cache-control"), "no-store");
    assert.equal(calls.length, 0);
    const malformed = await json(await handleReaderRequest(request(method, path, { cookies: cookieFor(signedIn({ siteSubject: personId })), body: method === "POST" ? "{}" : undefined }), action, harness().options));
    assert.equal(malformed.status, 503, `${action}: the global person id is never a subject`);
  }

  // No sealing secret configured: nobody can be signed in, still 503, never a bypass.
  {
    const { calls, options } = harness();
    const answer = await json(await handleReaderRequest(request("GET", "/api/reader/me", { cookies: cookieFor(signedIn()) }), "me", { ...options, loadSealingSecret: async () => null }));
    assert.equal(answer.status, 503);
    assert.equal(answer.body.error, "reader_identity_unavailable");
    assert.equal(calls.length, 0);
  }

  // Signed out: 401, so the island shows "Sign in".
  for (const cookies of [{}, { [PROSPECTUS_SESSION_COOKIE]: "v1.not-a-sealed-cookie" }, cookieFor(signedIn({ accessTokenExpiresAt: 1 }))]) {
    for (const [action, method, path] of [["me", "GET", "/api/reader/me"], ["vote", "POST", "/api/reader/vote"]] as const) {
      const { calls, options } = harness();
      const expired = Object.keys(cookies).length > 0 && cookies !== undefined ? { ...options, nowInSeconds: nowInSeconds + 99999 } : options;
      const answer = await json(await handleReaderRequest(request(method, path, { cookies, body: method === "POST" ? "{}" : undefined }), action, Object.keys(cookies).length === 0 ? options : expired));
      assert.equal(answer.status, 401, `${action} signed out`);
      assert.equal(answer.body.error, "signed_out");
      assert.equal(calls.length, 0);
    }
  }

  // Origin: a missing or foreign Origin is 403 on writes.
  for (const origin of ["https://evil.example", "http://reader.example.test", `${siteOrigin}:8443`, "null", ""]) {
    const { calls, options } = harness();
    const answer = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), origin, body: "{}" }), "vote", options));
    assert.equal(answer.status, 403, `origin ${origin}`);
    assert.equal(calls.length, 0);
  }
  {
    const { calls, options } = harness();
    const noOrigin = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), origin: null, body: "{}" }), "vote", options));
    assert.equal(noOrigin.status, 403, "a missing Origin fails closed");
    assert.equal(calls.length, 0);
  }

  // Content type and size.
  {
    const { calls, options } = harness();
    const wrongType = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), contentType: "text/plain", body: "{}" }), "vote", options));
    assert.equal(wrongType.status, 415);
    const noType = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), contentType: null, body: "{}" }), "vote", options));
    assert.equal(noType.status, 415);
    const tooBig = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), body: JSON.stringify({ pad: "x".repeat(4096) }) }), "vote", options));
    assert.equal(tooBig.status, 413);
    assert.equal(tooBig.body.error, "payload_too_large");
    const atTheLimit = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), body: JSON.stringify({ pad: "x".repeat(4096 - 10) }) }), "vote", options));
    assert.equal(atTheLimit.status, 200, "4096 bytes is allowed");
    const notJson = await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), body: "{nope" }), "vote", options));
    assert.equal(notJson.status, 400);
    for (const body of ["[]", "7", "null", '"x"']) {
      assert.equal((await json(await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn()), body }), "vote", options))).status, 400, `body ${body}`);
    }
    assert.equal(calls.length, 1, "only the request at the limit reached the function");
  }

  // The happy path: the function gets the subject, staff flag and payload; the response never carries the subject or the person id.
  {
    const { calls, options } = harness({ statusCode: 200, body: { readerId: "r-1", handle: null, karma: 0, state: "active", votes: {} } });
    const answer = await json(await handleReaderRequest(request("GET", "/api/reader/me?subjects=item-one,item-two", { cookies: cookieFor(signedIn()) }), "me", options));
    assert.equal(answer.status, 200);
    assert.equal(answer.headers.get("cache-control"), "no-store");
    assert.deepEqual(calls, [{ functionName: "reader-actions-test", event: { publication: "reader.example.test", siteSubject, isStaff: false, action: "me", payload: { subjects: ["item-one", "item-two"] } } }]);
    const text = JSON.stringify(answer.body);
    assert.equal(text.includes(siteSubject) || text.includes(personId), false);
  }
  {
    const groups = Buffer.from(JSON.stringify({ "cognito:groups": ["editor"] })).toString("base64url");
    const accessToken = `h.${groups}.s`;
    assert.equal(readerIsStaff({ accessToken }), true);
    const { calls, options } = harness();
    await handleReaderRequest(request("POST", "/api/reader/vote", { cookies: cookieFor(signedIn({ accessToken })), body: JSON.stringify({ subject: "item-one", dimension: "up", on: true, isStaff: false }) }), "vote", options);
    assert.equal(calls[0].event.isStaff, true, "staff comes from the session, never from the body");
    assert.deepEqual(calls[0].event.payload, { subject: "item-one", dimension: "up", on: true, isStaff: false });
  }

  // me validates the subjects it forwards.
  for (const query of ["subjects=a%23b", `subjects=${Array.from({ length: 51 }, (_, index) => `item-${index}`).join(",")}`, "subjects=a,,b", "subjects=a%20b"]) {
    const { calls, options } = harness();
    const answer = await json(await handleReaderRequest(request("GET", `/api/reader/me?${query}`, { cookies: cookieFor(signedIn()) }), "me", options));
    assert.equal(answer.status, 400, query);
    assert.equal(calls.length, 0);
  }
  {
    const { calls, options } = harness();
    await handleReaderRequest(request("GET", "/api/reader/me", { cookies: cookieFor(signedIn()) }), "me", options);
    assert.deepEqual(calls[0].event.payload, { subjects: [] });
  }

  // 429 carries Retry-After; other statuses pass through.
  {
    const { options } = harness({ statusCode: 429, body: { error: "rate_limited", message: "Too many actions.", retryAfter: 1800 } });
    const answer = await json(await handleReaderRequest(request("POST", "/api/reader/rating", { cookies: cookieFor(signedIn()), body: "{}" }), "rating", options));
    assert.equal(answer.status, 429);
    assert.equal(answer.body.retryAfter, 1800);
    assert.equal(answer.headers.get("retry-after"), "1800");
  }
  {
    const { options } = harness({ statusCode: 409, body: { error: "handle_taken", message: "That handle is taken." } });
    const answer = await json(await handleReaderRequest(request("POST", "/api/reader/handle", { cookies: cookieFor(signedIn()), body: JSON.stringify({ handle: "quiet-fox" }) }), "handle", options));
    assert.equal(answer.status, 409);
  }

  // Function failures are 502 without detail; a site without the plugin outputs is 503.
  {
    const { options } = harness();
    const failing = { ...options, invoke: async () => { throw new Error(`secret detail ${siteSubject}`); } };
    const originalError = console.error;
    const logged: string[] = [];
    console.error = (...args: unknown[]) => { logged.push(args.join(" ")); };
    try {
      const answer = await json(await handleReaderRequest(request("GET", "/api/reader/me", { cookies: cookieFor(signedIn()) }), "me", failing));
      assert.equal(answer.status, 502);
      assert.equal(JSON.stringify(answer.body).includes(siteSubject), false);
    } finally {
      console.error = originalError;
    }
    assert.equal(logged.length, 1);
    assert.equal(logged[0].includes(siteSubject) || logged[0].includes(personId), false, "no subject or person id in the log line");
    const noFunction = await json(await handleReaderRequest(request("GET", "/api/reader/me", { cookies: cookieFor(signedIn()) }), "me", { ...options, actionsFunctionName: null }));
    assert.equal(noFunction.status, 503);
    assert.equal(noFunction.body.error, "reader_actions_unavailable");
  }

  // An unconfigured site origin fails closed.
  {
    const { options } = harness();
    const answer = await json(await handleReaderRequest(request("GET", "/api/reader/me", { cookies: cookieFor(signedIn()) }), "me", { ...options, environment: { SITE_ENV: "production" } }));
    assert.equal(answer.status, 503);
    assert.equal(answer.body.error, "site_origin_not_configured");
  }

  // Development: the interim subject stands in, and it is what the function receives.
  {
    const { calls, options } = harness();
    await handleReaderRequest(request("GET", "/api/reader/me", { cookies: cookieFor(signedIn({ siteSubject: undefined })) }), "me", { ...options, environment: developmentEnvironment });
    assert.match(calls[0].event.siteSubject, /^ssdev_[A-Za-z0-9_-]{43}$/);
    assert.equal(calls[0].event.siteSubject.includes(personId), false);
  }

  console.log("reader api ok");
})();
