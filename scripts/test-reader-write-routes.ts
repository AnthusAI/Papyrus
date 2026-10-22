import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";
import { READER_BODY_BYTES_BY_ACTION, READER_MAXIMUM_BODY_BYTES, handleReaderRequest, type ReaderAction, type ReaderActionEvent, type ReaderActionResult } from "../lib/reader-api";

/**
 * The routes that carry reader text (submit, comment, edit, delete, report and flag) share
 * the fail-closed checks of the vote route: 503 without a siteSubject, 401 signed out, 403 for a foreign Origin,
 * 415, 413 above the action's body limit, 429 with Retry-After and pass-through of the function's answers.
 */
const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const siteOrigin = "https://reader.example.test";
const siteSubject = `ss1_${"C".repeat(43)}`;
const personId = "person-global-id-456";
const nowInSeconds = 1_000;
const environment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };

const bodies: Partial<Record<ReaderAction, Record<string, unknown>>> = {
  submit: { url: "https://example.com/post", title: "A small tool", note: "Worked well." },
  comment: { subject: "item-one", body: "Worth reading.", ratingContext: { dimension: "real", value: 4 } },
  "comment-edit": { id: "cmt-00000000000000000000000000000001", body: "Better words." },
  "comment-delete": { id: "cmt-00000000000000000000000000000001" },
  report: { target: "cmt-00000000000000000000000000000001", reason: "Looks like an advert." },
  flag: { subject: { type: "proposal", id: "prop-1" }, kind: "wrong", reason: "The figures do not match." },
};

function cookieFor(session: Record<string, unknown> | null): Record<string, string> {
  if (!session) return {};
  return { [PROSPECTUS_SESSION_COOKIE]: sealProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, session, nowInSeconds + 3600) };
}
const signedIn = (changes: Record<string, unknown> = {}) => ({ personId, accessToken: "x.y.z", accessTokenExpiresAt: nowInSeconds + 3600, siteSubject, ...changes });

function post(action: string, options: { cookies?: Record<string, string>; origin?: string | null; contentType?: string | null; body?: string } = {}): NextRequest {
  const cookie = Object.entries(options.cookies ?? {}).map(([name, value]) => `${name}=${value}`).join("; ");
  const headers: Record<string, string> = {};
  if (cookie) headers.cookie = cookie;
  if (options.origin !== null) headers.origin = options.origin ?? siteOrigin;
  if (options.contentType !== null) headers["content-type"] = options.contentType ?? "application/json";
  return new NextRequest(new URL(`/api/reader/${action}`, "https://localhost:3000"), { method: "POST", headers, body: options.body ?? "{}" });
}

function harness(result: ReaderActionResult = { statusCode: 200, body: { ok: true } }) {
  const calls: Array<{ functionName: string; event: ReaderActionEvent }> = [];
  return {
    calls,
    options: {
      environment: environment as Record<string, string | undefined>,
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
  for (const action of Object.keys(bodies) as ReaderAction[]) {
    const good = JSON.stringify(bodies[action]);
    const limit = READER_BODY_BYTES_BY_ACTION[action] ?? READER_MAXIMUM_BODY_BYTES;

    // 503: no siteSubject, or the global person id where a siteSubject belongs. Nothing is invoked.
    for (const session of [signedIn({ siteSubject: undefined }), signedIn({ siteSubject: personId })]) {
      const { calls, options } = harness();
      const answer = await json(await handleReaderRequest(post(action, { cookies: cookieFor(session), body: good }), action, options));
      assert.equal(answer.status, 503, `${action} without a siteSubject`);
      assert.equal(answer.body.error, "reader_identity_unavailable");
      assert.equal(answer.headers.get("cache-control"), "no-store");
      assert.equal(calls.length, 0);
    }

    // 401: signed out.
    {
      const { calls, options } = harness();
      const answer = await json(await handleReaderRequest(post(action, { body: good }), action, options));
      assert.equal(answer.status, 401, `${action} signed out`);
      assert.equal(answer.body.error, "signed_out");
      assert.equal(calls.length, 0);
    }

    // 403: a foreign or missing Origin.
    for (const origin of ["https://evil.example", "http://reader.example.test", "null", "", null]) {
      const { calls, options } = harness();
      const answer = await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), origin, body: good }), action, options));
      assert.equal(answer.status, 403, `${action} origin ${String(origin)}`);
      assert.equal(answer.body.error, "origin_mismatch");
      assert.equal(calls.length, 0);
    }

    // 415 and 400.
    {
      const { calls, options } = harness();
      assert.equal((await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), contentType: "text/plain", body: good }), action, options))).status, 415);
      assert.equal((await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), contentType: null, body: good }), action, options))).status, 415);
      assert.equal((await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: "{nope" }), action, options))).status, 400);
      assert.equal((await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: "[]" }), action, options))).status, 400);
      assert.equal(calls.length, 0);
    }

    // 413 above this action's limit; the limit itself passes.
    {
      const { calls, options } = harness();
      const over = await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: JSON.stringify({ pad: "x".repeat(limit) }) }), action, options));
      assert.equal(over.status, 413, `${action} over ${limit} bytes`);
      assert.equal(over.body.error, "payload_too_large");
      assert.equal(calls.length, 0);
      const exact = JSON.stringify({ pad: "x".repeat(limit - 10) });
      assert.equal(Buffer.byteLength(exact), limit);
      assert.equal((await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: exact }), action, options))).status, 200, `${action} at ${limit} bytes`);
      assert.equal(calls.length, 1);
    }

    // The function gets the subject, the staff flag and the payload; answers pass through; 429 carries Retry-After.
    {
      const { calls, options } = harness({ statusCode: 201, body: { subject: "sub-1", state: "pending" } });
      const answer = await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: good }), action, options));
      assert.equal(answer.status, 201);
      assert.deepEqual(calls, [{ functionName: "reader-actions-test", event: { publication: "reader.example.test", siteSubject, isStaff: false, action, payload: bodies[action] } }]);
      assert.equal(JSON.stringify(answer.body).includes(siteSubject) || JSON.stringify(answer.body).includes(personId), false);
    }
    {
      const { options } = harness({ statusCode: 429, body: { error: "rate_limited", message: "Too many actions.", retryAfter: 4000 } });
      const answer = await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: good }), action, options));
      assert.equal(answer.status, 429);
      assert.equal(answer.headers.get("retry-after"), "4000");
    }
    {
      const { options } = harness({ statusCode: 409, body: { error: "duplicate_submission", message: "That link was already submitted.", existing: { subject: "sub-1" } } });
      const answer = await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: good }), action, options));
      assert.equal(answer.status, 409);
      assert.deepEqual(answer.body.existing, { subject: "sub-1" });
    }
    {
      const { options } = harness();
      const failing = { ...options, invoke: async () => { throw new Error(`detail ${siteSubject}`); } };
      const originalError = console.error;
      console.error = () => {};
      try {
        const answer = await json(await handleReaderRequest(post(action, { cookies: cookieFor(signedIn()), body: good }), action, failing));
        assert.equal(answer.status, 502);
        assert.equal(JSON.stringify(answer.body).includes(siteSubject), false);
      } finally {
        console.error = originalError;
      }
    }
  }

  assert.ok(READER_BODY_BYTES_BY_ACTION.submit! > READER_MAXIMUM_BODY_BYTES, "a submission carries more text than a vote");
  assert.ok(READER_BODY_BYTES_BY_ACTION.comment! >= 4 * 2000 + 512, "a comment of 2,000 four-byte characters fits");
  assert.equal(READER_BODY_BYTES_BY_ACTION["comment-delete"], undefined, "a delete is as small as a vote");
  console.log("reader write routes ok");
})();
