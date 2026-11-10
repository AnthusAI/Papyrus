import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import {
  handleNotificationsConfirm,
  handleNotificationsPreferences,
  handleNotificationsState,
  handleNotificationsSubscribe,
  handleNotificationsUnsubscribe,
  type NotificationsApiOptions,
  type NotificationsEvent,
  type NotificationsResult,
} from "../lib/notifications-api";

const siteOrigin = "https://news.example.com";
const environment = { PAPYRUS_SITE_ORIGIN: siteOrigin, SITE_ENV: "production" };
const outputs = {
  custom: {
    papyrusPlugins: {
      notifications: {
        contract: 1,
        fromName: "Example News",
        basePath: "posts",
        lists: [{ id: "stories", name: "New stories", description: "" }],
        theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" },
      },
    },
    notifications: { actionsFunction: "notifications-fn" },
  },
};
const TOKEN = "tok.en_1-2";

function request(method: string, path: string, options: { headers?: Record<string, string>; origin?: string | null; contentType?: string | null; body?: string } = {}): NextRequest {
  const headers: Record<string, string> = { ...options.headers };
  if (method !== "GET" && method !== "HEAD") {
    if (options.origin !== null) headers.origin = options.origin ?? siteOrigin;
    if (options.contentType !== null) headers["content-type"] = options.contentType ?? "application/json";
  }
  return new NextRequest(new URL(path, "https://localhost:3000"), { method, headers, ...(options.body === undefined ? {} : { body: options.body }) });
}

const UNAVAILABLE: NotificationsResult = { statusCode: 503, body: { status: "unavailable" } };
function harness(result: NotificationsResult | ((event: NotificationsEvent) => NotificationsResult) = UNAVAILABLE, withOutputs: Record<string, unknown> | null = outputs) {
  const calls: Array<{ functionName: string; event: NotificationsEvent }> = [];
  const options: NotificationsApiOptions = {
    environment: environment as Record<string, string | undefined>,
    outputs: withOutputs,
    invoke: async (functionName, event) => {
      calls.push({ functionName, event });
      return typeof result === "function" ? result(event) : result;
    },
  };
  return { calls, options };
}
const location = (response: Response) => new URL(response.headers.get("location") ?? "");

(async () => {
  // A site without the plugin answers 404 on every route, and invokes nothing.
  for (const withOutputs of [null, { custom: {} }, { custom: { papyrusPlugins: { newsletter: {} } } }]) {
    const { calls, options } = harness(UNAVAILABLE, withOutputs);
    assert.equal((await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "{}" }), options)).status, 404);
    assert.equal((await handleNotificationsState(request("GET", "/api/notifications/state?kind=lists&lists=stories"), options)).status, 404);
    for (const handler of [handleNotificationsConfirm, handleNotificationsPreferences, handleNotificationsUnsubscribe]) {
      assert.equal((await handler(request("GET", `/api/notifications/x?t=${TOKEN}`), options)).status, 404);
    }
    assert.deepEqual(calls, []);
  }

  // A post from another origin is refused with a 400, and nothing is sent.
  {
    const { calls, options } = harness();
    for (const origin of ["https://evil.example", "null", null]) {
      const response = await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { origin, body: JSON.stringify({ email: "reader@example.test" }) }), options);
      assert.equal(response.status, 400);
      assert.equal((await response.json()).error, "origin_mismatch");
    }
    assert.deepEqual(calls, []);
    const confirm = await handleNotificationsConfirm(request("POST", "/api/notifications/confirm", { origin: "https://evil.example", contentType: "application/x-www-form-urlencoded", body: `t=${TOKEN}` }), options);
    assert.equal(confirm.status, 303, "a page post from elsewhere is a redirect to the expired page, never a 403");
    assert.equal(location(confirm).pathname, "/posts/notifications/expired/");
    assert.deepEqual(calls, []);
  }

  // Subscribe: invalid bodies, then the function's answer passes through (today: unavailable).
  {
    const { calls, options } = harness();
    assert.equal((await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { contentType: "text/plain", body: "x" }), options)).status, 415);
    assert.equal((await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "[1]" }), options)).status, 400);
    assert.equal((await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "x".repeat(9000) }), options)).status, 413);
    const response = await handleNotificationsSubscribe(
      request("POST", "/api/notifications/subscribe", { headers: { "user-agent": "agent", "cloudfront-viewer-address": "203.0.113.9:443" }, body: JSON.stringify({ email: "reader@example.test", lists: "stories,Bad Id", website: "", renderedAt: 5 }) }),
      options,
    );
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { status: "unavailable" });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].functionName, "notifications-fn");
    assert.deepEqual(calls[0].event, {
      action: "subscribe", email: "reader@example.test", lists: ["stories"], page: "", consent: "", formId: "", honeypot: "", renderedAt: 5, ip: "203.0.113.9", userAgent: "agent",
    });
    const failing = harness(() => {
      throw new Error("boom");
    });
    assert.equal((await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "{}" }), failing.options)).status, 502);
    const accepted = harness({ statusCode: 202, body: { status: "check_email", secret: "x" } });
    const ok = await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "{}" }), accepted.options);
    assert.deepEqual(await ok.json(), { status: "check_email" }, "only the status word is passed on");
  }

  // The environment names the function; without a function the routes answer 503, never a throw.
  {
    const { calls, options } = harness(UNAVAILABLE, { custom: { papyrusPlugins: outputs.custom.papyrusPlugins } });
    assert.equal((await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "{}" }), options)).status, 503);
    options.environment = { ...environment, PAPYRUS_NOTIFICATIONS_FUNCTION: "from-environment" };
    await handleNotificationsSubscribe(request("POST", "/api/notifications/subscribe", { body: "{}" }), options);
    assert.equal(calls[0].functionName, "from-environment");
  }

  // Confirm, preferences and unsubscribe: GET and HEAD change nothing and redirect (302) under the base path.
  for (const [handler, page, path] of [
    [handleNotificationsConfirm, "confirm", "confirm"],
    [handleNotificationsPreferences, "preferences", "preferences"],
    [handleNotificationsUnsubscribe, "unsubscribe", "unsubscribe"],
  ] as const) {
    const { calls, options } = harness();
    for (const method of ["GET", "HEAD"]) {
      const response = await handler(request(method, `/api/notifications/${path}?t=${TOKEN}`), options);
      assert.equal(response.status, 302);
      assert.equal(location(response).pathname, `/posts/notifications/${page}/`);
      assert.equal(location(response).searchParams.get("token"), TOKEN);
    }
    const missing = await handler(request("GET", `/api/notifications/${path}`), options);
    assert.equal(location(missing).pathname, "/posts/notifications/expired/");
    assert.deepEqual(calls, []);
  }

  // POSTs: the function's answer decides the redirect; "unavailable" is the expired page.
  {
    const form = { contentType: "application/x-www-form-urlencoded" };
    const { calls, options } = harness();
    const confirm = await handleNotificationsConfirm(request("POST", "/api/notifications/confirm", { ...form, body: `t=${TOKEN}` }), options);
    assert.equal(confirm.status, 303);
    assert.equal(location(confirm).pathname, "/posts/notifications/expired/");
    assert.deepEqual(calls[0].event.action, "confirm");
    const confirmed = await handleNotificationsConfirm(
      request("POST", "/api/notifications/confirm", { ...form, body: `t=${TOKEN}` }),
      harness({ statusCode: 200, body: { status: "confirmed", lists: [{ id: "stories" }], manageToken: "m.t" } }).options,
    );
    assert.equal(location(confirmed).pathname, "/posts/notifications/confirmed/");
    assert.equal(location(confirmed).searchParams.get("lists"), "stories");
    assert.equal(location(confirmed).searchParams.get("token"), "m.t");

    // One-click unsubscribe from a mail provider has no Origin and answers in plain text.
    const unsubscribed = harness({ statusCode: 200, body: { status: "unsubscribed", lists: [] } });
    const oneClick = await handleNotificationsUnsubscribe(
      request("POST", `/api/notifications/unsubscribe?t=${TOKEN}`, { origin: null, contentType: "application/x-www-form-urlencoded", body: "List-Unsubscribe=One-Click" }),
      unsubscribed.options,
    );
    assert.equal(oneClick.status, 200);
    assert.equal(await oneClick.text(), "Unsubscribed.");
    const bare = await handleNotificationsUnsubscribe(request("POST", `/api/notifications/unsubscribe?t=${TOKEN}`, { origin: null, contentType: "application/x-www-form-urlencoded", body: "" }), unsubscribed.options);
    assert.equal(bare.status, 400);
    const refused = await handleNotificationsUnsubscribe(request("POST", `/api/notifications/unsubscribe?t=${TOKEN}`, { origin: null, contentType: "application/x-www-form-urlencoded", body: "List-Unsubscribe=One-Click" }), harness().options);
    assert.equal(refused.status, 400, "the function said unavailable: the one-click post is not claimed done");

    const preferences = harness({ statusCode: 200, body: { status: "saved" } });
    const saved = await handleNotificationsPreferences(request("POST", "/api/notifications/preferences", { ...form, body: `t=${TOKEN}&action=save&l=stories&l=Bad%20Id` }), preferences.options);
    assert.equal(location(saved).searchParams.get("msg"), "saved");
    assert.deepEqual(preferences.calls[0].event, { action: "update_preferences", token: TOKEN, lists: ["stories"] });
    const step = await handleNotificationsPreferences(request("POST", "/api/notifications/preferences", { ...form, body: `t=${TOKEN}&action=delete` }), preferences.options);
    assert.equal(location(step).searchParams.get("step"), "delete");
    assert.equal(preferences.calls.length, 1, "deleting waits for the confirm step");
    const invalid = await handleNotificationsPreferences(request("POST", "/api/notifications/preferences", { ...form, body: `t=${TOKEN}&action=other` }), preferences.options);
    assert.equal(invalid.status, 400);
  }

  // State: lists come from the site's own settings; the rest asks the function. Failures are 400, 502 or 503, never 403 or 404.
  {
    const { calls, options } = harness();
    const lists = await handleNotificationsState(request("GET", "/api/notifications/state?kind=lists&lists=stories,missing,Bad%20Id"), options);
    assert.deepEqual(await lists.json(), { status: "ready", lists: [{ id: "stories", name: "New stories" }] });
    assert.equal((await handleNotificationsState(request("GET", "/api/notifications/state?kind=other"), options)).status, 400);
    assert.equal((await handleNotificationsState(request("GET", "/api/notifications/state?kind=confirm"), options)).status, 400);
    const unavailable = await handleNotificationsState(request("GET", `/api/notifications/state?kind=confirm&t=${TOKEN}`), options);
    assert.equal(unavailable.status, 503);
    assert.deepEqual(await unavailable.json(), { status: "unavailable" });
    assert.equal(calls[0].event.action, "confirm_page_state");
    const ready = harness({ statusCode: 200, body: { status: "ready", email: "r***@example.test", lists: [{ id: "stories", name: "New stories", subscribed: true, internal: 1 }] } });
    const preferences = await handleNotificationsState(request("GET", `/api/notifications/state?kind=preferences&t=${TOKEN}`), ready.options);
    assert.deepEqual(await preferences.json(), { status: "ready", email: "r***@example.test", lists: [{ id: "stories", name: "New stories", description: "", subscribed: true }] });
  }

  console.log("notifications api ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
