import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import {
  clientAddress,
  handleNewsletterConfirm,
  handleNewsletterPreferences,
  handleNewsletterState,
  handleNewsletterSubscribe,
  handleNewsletterUnsubscribe,
  isSameSiteRequest,
  type NewsletterApiOptions,
  type NewsletterEvent,
  type NewsletterResult,
} from "../lib/newsletter-api";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie } from "../lib/prospectus-session";

const siteOrigin = "https://news.example.com";
const environment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };
const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const siteSubject = `ss1_${"C".repeat(43)}`;
const nowInSeconds = 1_000;
const outputs = {
  custom: {
    papyrusPlugins: {
      newsletter: {
        contract: 1,
        fromName: "Example News",
        lists: [
          { id: "weekly", name: "Weekly roundup", description: "", kind: "roundup" },
          { id: "alerts-x", name: "Alerts", description: "", kind: "alert" },
        ],
        theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" },
      },
    },
    newsletter: { actionsFunction: "newsletter-fn" },
  },
};

function request(method: string, path: string, options: { headers?: Record<string, string>; origin?: string | null; contentType?: string | null; body?: string } = {}): NextRequest {
  const headers: Record<string, string> = { ...options.headers };
  if (method !== "GET" && method !== "HEAD") {
    if (options.origin !== null) headers.origin = options.origin ?? siteOrigin;
    if (options.contentType !== null) headers["content-type"] = options.contentType ?? "application/json";
  }
  return new NextRequest(new URL(path, "https://localhost:3000"), { method, headers, ...(options.body === undefined ? {} : { body: options.body }) });
}

function harness(result: NewsletterResult | ((event: NewsletterEvent) => NewsletterResult) = { statusCode: 202, body: { status: "check_email" } }) {
  const calls: Array<{ functionName: string; event: NewsletterEvent }> = [];
  return {
    calls,
    options: {
      environment: environment as Record<string, string | undefined>,
      outputs: outputs as Record<string, unknown> | null,
      nowInSeconds,
      loadSealingSecret: async () => sealingSecret as string | null,
      invoke: async (functionName: string, event: NewsletterEvent) => {
        calls.push({ functionName, event });
        return typeof result === "function" ? result(event) : result;
      },
    },
  };
}

const subscribeBody = (changes: Record<string, unknown> = {}) =>
  JSON.stringify({ email: "reader@example.com", lists: ["weekly"], page: "https://news.example.com/roundup/", website: "", renderedAt: 123, consent: "Yes.", formId: "newsletter", ...changes });

(async () => {
  // Not enabled: 404 everywhere, nothing invoked.
  for (const disabled of [{}, null, { custom: {} }, { custom: { papyrusPlugins: { signup: { forms: [] } } } }]) {
    const { calls, options } = harness();
    const subscribe = await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { body: subscribeBody() }), { ...options, outputs: disabled });
    assert.equal(subscribe.status, 404);
    assert.equal((await handleNewsletterConfirm(request("GET", "/api/newsletter/confirm?t=abc"), { ...options, outputs: disabled })).status, 404);
    assert.equal(
      (await handleNewsletterConfirm(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", body: "t=abc" }), { ...options, outputs: disabled })).status,
      404,
    );
    assert.equal((await handleNewsletterState(request("GET", "/api/newsletter/state?kind=lists"), { ...options, outputs: disabled })).status, 404);
    assert.equal(calls.length, 0);
  }

  // Subscribe: the event the function gets.
  {
    const { calls, options } = harness();
    const response = await handleNewsletterSubscribe(
      request("POST", "/api/newsletter/subscribe", {
        headers: { "cloudfront-viewer-address": "198.51.100.7:51234", "user-agent": "U".repeat(500), "x-forwarded-for": "203.0.113.1" },
        body: subscribeBody({ lists: "weekly, alerts-x ,BAD list", email: "x".repeat(400), website: "http://spam.example" }),
      }),
      options,
    );
    assert.equal(response.status, 202);
    assert.deepEqual(await response.json(), { status: "check_email" });
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(calls.length, 1);
    const { functionName, event } = calls[0];
    assert.equal(functionName, "newsletter-fn");
    assert.equal(event.action, "subscribe");
    assert.deepEqual(event.lists, ["weekly", "alerts-x"], "a comma string is accepted and malformed ids are dropped");
    assert.equal((event.email as string).length, 320);
    assert.equal(event.ip, "198.51.100.7");
    assert.equal((event.userAgent as string).length, 300);
    assert.equal(event.honeypot, "http://spam.example");
    assert.equal(event.renderedAt, 123);
    assert.equal(event.consent, "Yes.");
    assert.equal("siteSubject" in event, false, "no session, no subject");
  }
  // Lists as an array; a lambda refusal passes through and only its status does.
  {
    const { calls, options } = harness({ statusCode: 400, body: { status: "invalid_email", detail: "secret" } });
    const response = await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { body: subscribeBody({ lists: ["weekly", "alerts-x"] }) }), options);
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { status: "invalid_email" });
    assert.deepEqual(calls[0].event.lists, ["weekly", "alerts-x"]);
  }

  // The optional site subject: sent when signed in, never required, never an error.
  {
    const cookie = sealProspectusCookie(
      sealingSecret,
      PROSPECTUS_SESSION_COOKIE,
      { personId: "person-1", accessToken: "x.y.z", accessTokenExpiresAt: nowInSeconds + 3600, siteSubject },
      nowInSeconds + 3600,
    );
    const signedIn = harness();
    await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { headers: { cookie: `${PROSPECTUS_SESSION_COOKIE}=${cookie}` }, body: subscribeBody() }), signedIn.options);
    assert.equal(signedIn.calls[0].event.siteSubject, siteSubject);
    const broken = harness();
    const unavailable = await handleNewsletterSubscribe(
      request("POST", "/api/newsletter/subscribe", { headers: { cookie: `${PROSPECTUS_SESSION_COOKIE}=${cookie}` }, body: subscribeBody() }),
      { ...broken.options, loadSealingSecret: async () => { throw new Error("ssm down"); } },
    );
    assert.equal(unavailable.status, 202, "a failing identity lookup never blocks a signup");
    assert.equal("siteSubject" in broken.calls[0].event, false);
    const junk = harness();
    await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { headers: { cookie: `${PROSPECTUS_SESSION_COOKIE}=garbage` }, body: subscribeBody() }), junk.options);
    assert.equal("siteSubject" in junk.calls[0].event, false);
  }

  // Subscribe refusals.
  {
    const { calls, options } = harness();
    const post = (init: Parameters<typeof request>[2]) => handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", init), options);
    assert.equal((await post({ body: subscribeBody(), origin: "https://evil.example" })).status, 400);
    assert.equal((await post({ body: subscribeBody(), origin: null })).status, 400);
    assert.equal((await post({ body: subscribeBody(), contentType: "text/plain" })).status, 415);
    assert.equal((await post({ body: "x".repeat(9000) })).status, 413);
    assert.equal((await post({ body: "x".repeat(9000), headers: { "content-length": "9000" } })).status, 413);
    assert.equal((await post({ body: "not json" })).status, 400);
    assert.equal((await post({ body: "[1]" })).status, 400);
    assert.equal(calls.length, 0);
    const noOrigin = await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { body: subscribeBody() }), { ...options, environment: { SITE_ENV: "production" } });
    assert.equal(noOrigin.status, 503);
    const noFunction = await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { body: subscribeBody() }), {
      ...options,
      outputs: { custom: { papyrusPlugins: outputs.custom.papyrusPlugins } },
    });
    assert.equal(noFunction.status, 503);
    const failing = await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { body: subscribeBody() }), {
      ...options,
      invoke: async () => { throw new Error("boom"); },
    });
    assert.equal(failing.status, 502);
    const viaEnvironment = harness();
    await handleNewsletterSubscribe(request("POST", "/api/newsletter/subscribe", { body: subscribeBody() }), {
      ...viaEnvironment.options,
      environment: { ...environment, PAPYRUS_NEWSLETTER_FUNCTION: "from-env" },
    });
    assert.equal(viaEnvironment.calls[0].functionName, "from-env");
  }

  // Client address.
  {
    const get = (headers: Record<string, string>) => clientAddress(new Headers(headers));
    assert.equal(get({ "cloudfront-viewer-address": "198.51.100.7:51234" }), "198.51.100.7");
    assert.equal(get({ "cloudfront-viewer-address": "[2001:db8::1]:443" }), "2001:db8::1");
    assert.equal(get({ "cloudfront-viewer-address": "2001:db8::1:51234" }), "2001:db8::1");
    assert.equal(get({ "cloudfront-viewer-address": "198.51.100.7" }), "198.51.100.7");
    assert.equal(get({ "x-forwarded-for": "203.0.113.5, 10.0.0.1" }), "203.0.113.5");
    assert.equal(get({ "cloudfront-viewer-address": "garbage", "x-forwarded-for": "203.0.113.5" }), "203.0.113.5");
    assert.equal(get({ "x-forwarded-for": "not-an-ip" }), "unknown");
    assert.equal(get({}), "unknown");
  }

  // isSameSiteRequest: Origin first, Referer only when there is no Origin, null never.
  {
    const headers = (init: Record<string, string>) => new Headers(init);
    assert.equal(isSameSiteRequest(headers({ origin: siteOrigin }), siteOrigin), true);
    assert.equal(isSameSiteRequest(headers({ origin: "null" }), siteOrigin), false);
    assert.equal(isSameSiteRequest(headers({ origin: "null", referer: `${siteOrigin}/p` }), siteOrigin), false, "a null origin is not rescued by a referer");
    assert.equal(isSameSiteRequest(headers({ origin: "https://evil.example", referer: `${siteOrigin}/p` }), siteOrigin), false);
    assert.equal(isSameSiteRequest(headers({ referer: `${siteOrigin}/newsletter/confirm/?token=x` }), siteOrigin), true);
    assert.equal(isSameSiteRequest(headers({ referer: `${siteOrigin}.evil.example/p` }), siteOrigin), false);
    assert.equal(isSameSiteRequest(headers({ referer: "not a url" }), siteOrigin), false);
    assert.equal(isSameSiteRequest(headers({}), siteOrigin), false);
  }

  await humanPageTests();
  await stateTests();
  await machineTests();
  console.log("newsletter api ok");
})();

const manage = "v1.manage.token";
const formInit = (body: string, extra: Record<string, string | null> = {}) => ({ contentType: "application/x-www-form-urlencoded", body, ...extra });
const unsubscribed = { statusCode: 200, body: { status: "unsubscribed", scope: "all", lists: [{ id: "weekly", name: "Weekly roundup" }] } };
const withBase = (base: string): Record<string, unknown> => ({
  custom: { ...outputs.custom, papyrusPlugins: { newsletter: { ...outputs.custom.papyrusPlugins.newsletter, basePath: base } } },
});

function redirect(response: Response): { status: number; path: string; query: Record<string, string>; referrerPolicy: string | null } {
  const location = new URL(response.headers.get("location") ?? "", "https://invalid.example");
  assert.equal(location.origin, siteOrigin, "every redirect stays on the site");
  assert.ok(!location.pathname.startsWith("/api"), `a person is never sent to an /api URL: ${location.pathname}`);
  return { status: response.status, path: location.pathname, query: Object.fromEntries(location.searchParams), referrerPolicy: response.headers.get("referrer-policy") };
}

/** Every route a person's browser can reach answers with a redirect to a clean page of the site. */
async function humanPageTests() {
  // Old emails: GET on the human URLs redirects, changes nothing and asks nothing.
  {
    const h = harness();
    const get = (handler: typeof handleNewsletterConfirm, path: string) => handler(request("GET", path), h.options);
    assert.deepEqual(redirect(await get(handleNewsletterConfirm, "/api/newsletter/confirm?t=v1.abc.def")), { status: 302, path: "/newsletter/confirm/", query: { token: "v1.abc.def" }, referrerPolicy: "no-referrer" });
    assert.deepEqual(redirect(await get(handleNewsletterPreferences, `/api/newsletter/preferences?t=${manage}&msg=saved`)), { status: 302, path: "/newsletter/preferences/", query: { token: manage }, referrerPolicy: "no-referrer" });
    assert.deepEqual(redirect(await get(handleNewsletterUnsubscribe, `/api/newsletter/unsubscribe?t=${manage}`)), { status: 302, path: "/newsletter/unsubscribe/", query: { token: manage }, referrerPolicy: "no-referrer" });
    assert.deepEqual(redirect(await get(handleNewsletterUnsubscribe, `/api/newsletter/unsubscribe?t=${manage}&l=alerts-x`)).query, { token: manage, list: "alerts-x" });
    assert.equal(redirect(await get(handleNewsletterUnsubscribe, `/api/newsletter/unsubscribe?t=${manage}&l=BAD!`)).query.list, undefined, "a malformed list id is dropped");
    for (const [handler, route] of [[handleNewsletterConfirm, "confirm"], [handleNewsletterPreferences, "preferences"], [handleNewsletterUnsubscribe, "unsubscribe"]] as const) {
      for (const bad of [`/api/newsletter/${route}`, `/api/newsletter/${route}?t=%3Cscript%3E`]) {
        assert.deepEqual(redirect(await get(handler, bad)), { status: 302, path: "/newsletter/expired/", query: {}, referrerPolicy: "no-referrer" });
      }
    }
    assert.equal(h.calls.length, 0, "a GET never reaches the function");
  }

  // A mail scanner's HEAD on the legacy links answers exactly like GET, with no body, and never reaches the function.
  {
    const h = harness();
    for (const path of ["/api/newsletter/confirm?t=v1.abc.def", `/api/newsletter/preferences?t=${manage}`, `/api/newsletter/unsubscribe?t=${manage}&l=alerts-x`, "/api/newsletter/confirm", "/api/newsletter/unsubscribe?t=%3Cscript%3E"]) {
      const handler = path.includes("/confirm") ? handleNewsletterConfirm : path.includes("/preferences") ? handleNewsletterPreferences : handleNewsletterUnsubscribe;
      const get = await handler(request("GET", path), h.options);
      const head = await handler(request("HEAD", path), h.options);
      assert.equal(head.status, 302, path);
      assert.equal(head.headers.get("location"), get.headers.get("location"), path);
      assert.deepEqual(redirect(head), redirect(get), path);
      assert.equal(await head.text(), "", `HEAD has no body: ${path}`);
    }
    assert.equal(h.calls.filter((call) => ["confirm", "unsubscribe", "update_preferences", "delete_subscriber"].includes(String(call.event.action))).length, 0, "HEAD never mutates");
    assert.equal(h.calls.length, 0, "HEAD never reaches the function");
  }

  // Confirm POST: 303 to confirmed, carrying the lists and the manage token.
  {
    const h = harness({ statusCode: 200, body: { status: "confirmed", lists: [{ id: "weekly", name: "Weekly" }, { id: "alerts-x", name: "Alerts" }, { id: "BAD!", name: "x" }], manageToken: manage } });
    const response = await handleNewsletterConfirm(
      request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", headers: { "cloudfront-viewer-address": "198.51.100.9:1111", "user-agent": "Mail Client/1" }, body: "t=v1.abc.def" }),
      h.options,
    );
    assert.deepEqual(redirect(response), { status: 303, path: "/newsletter/confirmed/", query: { lists: "weekly,alerts-x", token: manage }, referrerPolicy: "no-referrer" });
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(h.calls[0].event, { action: "confirm", token: "v1.abc.def", ip: "198.51.100.9", userAgent: "Mail Client/1" });
  }
  // Confirm POST errors all land on the expired page; only transport problems (type, size) answer JSON, and a browser form cannot cause those.
  {
    const h = harness({ statusCode: 410, body: { status: "expired" } });
    const post = (init: Parameters<typeof request>[2]) => handleNewsletterConfirm(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", ...init }), h.options);
    for (const init of [{ body: "t=v1.abc.def" }, { body: "t=v1.abc.def", origin: "https://evil.example" }, { body: "t=v1.abc.def", origin: null }, { body: "x=1" }, { body: "t=%3Cscript%3E" }]) {
      assert.deepEqual(redirect(await post(init)), { status: 303, path: "/newsletter/expired/", query: {}, referrerPolicy: "no-referrer" }, JSON.stringify(init));
    }
    assert.equal(h.calls.length, 1, "only the one well formed same-site request reached the function");
    assert.equal((await post({ body: "t=v1.abc.def", contentType: "application/json" })).status, 415);
    assert.equal((await post({ body: "t=" + "a".repeat(5000) })).status, 413);
    const failing = await handleNewsletterConfirm(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", body: "t=abc" }), { ...h.options, invoke: async () => { throw new Error("boom"); } });
    assert.equal(redirect(failing).path, "/newsletter/expired/");
    const noFunction = await handleNewsletterConfirm(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", body: "t=abc" }), { ...h.options, outputs: { custom: { papyrusPlugins: outputs.custom.papyrusPlugins } } });
    assert.equal(redirect(noFunction).path, "/newsletter/expired/");
  }

  // Unsubscribe from the page: 303 to unsubscribed with the lists and the token (for the way back to preferences).
  {
    const h = harness(unsubscribed);
    const done = await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit(`t=${manage}&l=weekly&page=1`)), h.options);
    assert.deepEqual(redirect(done), { status: 303, path: "/newsletter/unsubscribed/", query: { lists: "weekly", token: manage }, referrerPolicy: "no-referrer" });
    assert.deepEqual(h.calls[0].event, { action: "unsubscribe", token: manage, list: "weekly" });
    const invalid = await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit("t=%22%3E&page=1")), h.options);
    assert.equal(redirect(invalid).path, "/newsletter/expired/");
    const rejected = await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit(`t=${manage}&page=1`)), { ...h.options, invoke: async () => ({ statusCode: 400, body: { status: "invalid" } }) });
    assert.equal(redirect(rejected).path, "/newsletter/expired/");
    const failing = await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit(`t=${manage}&page=1`)), { ...h.options, invoke: async () => { throw new Error("boom"); } });
    assert.equal(redirect(failing).path, "/newsletter/expired/");
  }

  // Preferences POST: save, unsubscribe from everything, delete with a confirm step, and the errors.
  {
    const saved = harness({ statusCode: 200, body: { status: "saved", lists: ["weekly"] } });
    const save = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save&l=weekly&l=alerts-x&l=BAD!`)), saved.options);
    assert.deepEqual(redirect(save), { status: 303, path: "/newsletter/preferences/", query: { token: manage, msg: "saved" }, referrerPolicy: "no-referrer" });
    assert.deepEqual(saved.calls[0].event, { action: "update_preferences", token: manage, lists: ["weekly", "alerts-x"] });

    const none = harness({ statusCode: 200, body: { status: "saved", lists: [] } });
    await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), none.options);
    assert.deepEqual(none.calls[0].event, { action: "update_preferences", token: manage, lists: [] }, "unticking everything saves an empty set");

    const all = harness(unsubscribed);
    const out = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=unsubscribe_all`)), all.options);
    assert.deepEqual(redirect(out).query, { token: manage, msg: "unsubscribed" });
    assert.deepEqual(all.calls[0].event, { action: "unsubscribe", token: manage });

    const deletion = harness({ statusCode: 200, body: { status: "deleted" } });
    const confirmStep = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=delete`)), deletion.options);
    assert.deepEqual(redirect(confirmStep), { status: 303, path: "/newsletter/preferences/", query: { token: manage, step: "delete" }, referrerPolicy: "no-referrer" });
    assert.equal(deletion.calls.length, 0, "nothing is deleted before the confirm step");
    const done = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=delete&confirm=1`)), deletion.options);
    assert.deepEqual(redirect(done).query, { msg: "deleted" }, "the deleted state carries no token");
    assert.deepEqual(deletion.calls[0].event, { action: "delete_subscriber", token: manage });

    const h = harness(unsubscribed);
    const post = (init: ReturnType<typeof formInit>) => handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", init), h.options);
    for (const init of [formInit(`t=${manage}&action=save`, { origin: "https://evil.example" }), formInit(`t=${manage}&action=save`, { origin: null }), formInit("action=save")]) {
      assert.equal(redirect(await post(init)).path, "/newsletter/expired/");
    }
    assert.equal((await post(formInit(`t=${manage}&action=save`, { contentType: "application/json" }))).status, 415);
    assert.equal((await post(formInit("t=" + manage + "&x=" + "a".repeat(5000)))).status, 413);
    assert.equal((await post(formInit(`t=${manage}&action=explode`))).status, 400);
    assert.equal(h.calls.length, 0);
    const rejected = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), { ...h.options, invoke: async () => ({ statusCode: 400, body: { status: "invalid" } }) });
    assert.equal(redirect(rejected).path, "/newsletter/expired/");
    const failing = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), { ...h.options, invoke: async () => { throw new Error("boom"); } });
    assert.equal(redirect(failing).path, "/newsletter/expired/");
  }

  // A site under a base path: every redirect lives under it; the machine endpoints do not.
  {
    const h = harness({ statusCode: 200, body: { status: "confirmed", lists: [{ id: "weekly", name: "Weekly" }], manageToken: manage } });
    const options: NewsletterApiOptions = { ...h.options, outputs: withBase("posts") };
    assert.equal(redirect(await handleNewsletterConfirm(request("GET", "/api/newsletter/confirm?t=v1.abc.def"), options)).path, "/posts/newsletter/confirm/");
    assert.equal(redirect(await handleNewsletterConfirm(request("POST", "/api/newsletter/confirm", formInit("t=v1.abc.def")), options)).path, "/posts/newsletter/confirmed/");
    assert.equal(redirect(await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), options)).path, "/posts/newsletter/expired/" /* the stub answers confirmed, not saved */);
    assert.equal(redirect(await handleNewsletterUnsubscribe(request("GET", `/api/newsletter/unsubscribe?t=${manage}`), options)).path, "/posts/newsletter/unsubscribe/");
    // An unusable base path is ignored, never injected into a redirect.
    for (const bad of ["../x", "/evil.example", "//evil.example", 7, "a b"]) {
      const odd = await handleNewsletterConfirm(request("GET", "/api/newsletter/confirm?t=v1.abc.def"), { ...h.options, outputs: withBase(bad as string) });
      assert.equal(redirect(odd).path, "/newsletter/confirm/", `base path ${String(bad)} is ignored`);
    }
  }

  // No public origin configured: 503 JSON, never a redirect to localhost.
  {
    const h = harness();
    const response = await handleNewsletterConfirm(request("GET", "/api/newsletter/confirm?t=abc"), { ...h.options, environment: { SITE_ENV: "production" } });
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("location"), null);
  }
}

async function stateTests() {
  const get = (path: string, options: NewsletterApiOptions) => handleNewsletterState(request("GET", path), options);
  const ready = { statusCode: 200, body: { status: "ready", email: "r***@example.com", lists: [
    { id: "weekly", name: "Weekly roundup", description: "The week.", subscribed: true },
    { id: "alerts-x", name: "Alerts", description: "", subscribed: false },
  ] } };

  // Preferences state: JSON, read only.
  {
    const h = harness(ready);
    const response = await get(`/api/newsletter/state?kind=preferences&t=${manage}`, h.options);
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^application\/json/);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), {
      status: "ready",
      email: "r***@example.com",
      lists: [
        { id: "weekly", name: "Weekly roundup", description: "The week.", subscribed: true },
        { id: "alerts-x", name: "Alerts", description: "", subscribed: false },
      ],
    });
    assert.deepEqual(h.calls.map((call) => call.event), [{ action: "preferences_state", token: manage }]);
    const invalid = await get(`/api/newsletter/state?kind=preferences&t=${manage}`, { ...h.options, invoke: async () => ({ statusCode: 400, body: { status: "invalid" } }) });
    assert.equal(invalid.status, 400);
    assert.deepEqual(await invalid.json(), { status: "invalid" });
  }
  // Confirm state: names only; it never confirms.
  {
    const h = harness({ statusCode: 200, body: { status: "ready", lists: [{ id: "weekly", name: "Weekly roundup" }] } });
    const response = await get("/api/newsletter/state?kind=confirm&t=v1.abc.def", h.options);
    assert.deepEqual(await response.json(), { status: "ready", lists: [{ name: "Weekly roundup" }] });
    assert.deepEqual(h.calls.map((call) => call.event.action), ["confirm_page_state"]);
    const expired = await get("/api/newsletter/state?kind=confirm&t=v1.abc.def", { ...h.options, invoke: async () => ({ statusCode: 410, body: { status: "expired" } }) });
    assert.equal(expired.status, 400, "the edge masks 403 and 404, so an invalid link answers 400");
  }
  // List names come from the site's own settings; unknown ids are dropped; the function is not asked.
  {
    const h = harness();
    const response = await get("/api/newsletter/state?kind=lists&lists=weekly,nope,alerts-x,BAD!", h.options);
    assert.deepEqual(await response.json(), { status: "ready", lists: [{ id: "weekly", name: "Weekly roundup" }, { id: "alerts-x", name: "Alerts" }] });
    assert.equal(h.calls.length, 0);
  }
  // Refusals.
  {
    const h = harness(ready);
    for (const path of ["/api/newsletter/state", "/api/newsletter/state?kind=other", "/api/newsletter/state?kind=preferences", "/api/newsletter/state?kind=preferences&t=%3Cx%3E"]) {
      assert.equal((await get(path, h.options)).status, 400, path);
    }
    assert.equal(h.calls.length, 0, "a missing or malformed token never reaches the function");
    const unavailable = await get(`/api/newsletter/state?kind=preferences&t=${manage}`, { ...h.options, invoke: async () => { throw new Error("boom"); } });
    assert.equal(unavailable.status, 502);
    const noFunction = await get(`/api/newsletter/state?kind=preferences&t=${manage}`, { ...h.options, outputs: { custom: { papyrusPlugins: outputs.custom.papyrusPlugins } } });
    assert.equal(noFunction.status, 503);
  }
}

/** The machine endpoints keep their contracts. */
async function machineTests() {
  // RFC 8058 one-click: a cross-origin POST (or none) with the marker and the token in the query. Tiny body, 200, idempotent, no redirect.
  {
    const { calls, options } = harness(unsubscribed);
    for (const origin of [null, "https://mail.example.org", siteOrigin]) {
      const response = await handleNewsletterUnsubscribe(
        request("POST", `/api/newsletter/unsubscribe?t=${manage}&l=alerts-x`, formInit("List-Unsubscribe=One-Click", { origin })),
        options,
      );
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("location"), null, "one-click never redirects");
      assert.equal(await response.text(), "Unsubscribed.");
      assert.match(response.headers.get("content-type") ?? "", /^text\/plain/);
    }
    assert.equal(calls.length, 3, "every repeat reaches the idempotent function");
    assert.deepEqual(calls[0].event, { action: "unsubscribe", token: manage, list: "alerts-x" });
    await handleNewsletterUnsubscribe(request("POST", `/api/newsletter/unsubscribe?t=${manage}`, formInit("List-Unsubscribe=One-Click", { origin: null })), options);
    assert.deepEqual(calls[3].event, { action: "unsubscribe", token: manage });
    // A mail provider may send any content type.
    const odd = await handleNewsletterUnsubscribe(request("POST", `/api/newsletter/unsubscribe?t=${manage}`, { contentType: "text/plain", origin: null, body: "List-Unsubscribe=One-Click" }), options);
    assert.equal(odd.status, 200);
    // Neither the marker nor our page: refused. Oversized: refused.
    assert.equal((await handleNewsletterUnsubscribe(request("POST", `/api/newsletter/unsubscribe?t=${manage}`, formInit("x=1")), options)).status, 400);
    assert.equal((await handleNewsletterUnsubscribe(request("POST", `/api/newsletter/unsubscribe?t=${manage}`, formInit("List-Unsubscribe=One-Click&x=" + "a".repeat(5000))), options)).status, 413);
    assert.equal((await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit("List-Unsubscribe=One-Click")), options)).status, 400);
    const refused = await handleNewsletterUnsubscribe(request("POST", `/api/newsletter/unsubscribe?t=${manage}`, formInit("List-Unsubscribe=One-Click")), {
      ...options,
      invoke: async () => ({ statusCode: 400, body: { status: "invalid" } }),
    });
    assert.equal(refused.status, 400);
    const failing = await handleNewsletterUnsubscribe(request("POST", `/api/newsletter/unsubscribe?t=${manage}`, formInit("List-Unsubscribe=One-Click")), {
      ...options,
      invoke: async () => { throw new Error("boom"); },
    });
    assert.equal(failing.status, 502, "a mail provider retries");
  }

  // The subscribe route shares the same-origin rule and also avoids 403 (the edge would mask it).
  {
    const { options, calls } = harness();
    const subscribe = (headers: Record<string, string>) =>
      handleNewsletterSubscribe(
        new NextRequest(`${siteOrigin}/api/newsletter/subscribe`, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify({ email: "reader@example.com", lists: ["weekly"], renderedAt: 1, website: "" }) }),
        options,
      );
    assert.equal((await subscribe({ origin: "null" })).status, 400);
    assert.equal((await subscribe({})).status, 400);
    assert.equal((await subscribe({ origin: siteOrigin })).status, 202);
    assert.equal((await subscribe({ referer: `${siteOrigin}/roundup/` })).status, 202);
    assert.equal(calls.length, 2);
  }
}
