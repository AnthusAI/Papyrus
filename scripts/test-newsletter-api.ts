import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import {
  clientAddress,
  handleNewsletterConfirmPage,
  handleNewsletterConfirmPost,
  handleNewsletterPreferences,
  handleNewsletterSubscribe,
  handleNewsletterUnsubscribe,
  type NewsletterEvent,
  type NewsletterResult,
} from "../lib/newsletter-api";
import { escapeHtml, pageTheme, renderPage } from "../lib/newsletter-pages";
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
        fromName: 'Example <b>"News"</b>',
        lists: [
          { id: "weekly", name: "Weekly <i>roundup</i>", description: "", kind: "roundup" },
          { id: "alerts-x", name: "Alerts", description: "", kind: "alert" },
        ],
        theme: { accent: "#aa3300", text: "#111111", background: "#ffffff", fontFamily: "x; } body { display:none" },
      },
    },
    newsletter: { actionsFunction: "newsletter-fn" },
  },
};

function request(method: string, path: string, options: { headers?: Record<string, string>; origin?: string | null; contentType?: string | null; body?: string } = {}): NextRequest {
  const headers: Record<string, string> = { ...options.headers };
  if (method !== "GET") {
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
      fetchShell: async () => ({ status: 404, contentType: "text/html", text: "" }),
      now: () => 0,
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
    assert.equal((await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?t=abc"), { ...options, outputs: disabled })).status, 404);
    assert.equal(
      (await handleNewsletterConfirmPost(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", body: "t=abc" }), { ...options, outputs: disabled })).status,
      404,
    );
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

  // Confirm page: GET never confirms.
  {
    const { calls, options } = harness({ statusCode: 200, body: { status: "ready", lists: [{ id: "weekly", name: "Weekly <i>roundup</i>" }] } });
    const page = await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?t=v1.abc.def"), options);
    const html = await page.text();
    assert.equal(page.status, 200);
    assert.deepEqual(calls.map((call) => call.event.action), ["confirm_page_state"], "the page only reads");
    assert.match(html, /<form class="markus-newsletter-form" method="post" action="\/api\/newsletter\/confirm">/);
    assert.match(html, /name="t" value="v1.abc.def"/);
    assert.match(html, /Confirm subscription/);
    assert.match(html, /<meta name="robots" content="noindex">/);
    assert.equal(page.headers.get("cache-control"), "no-store");
    assert.match(page.headers.get("content-type") ?? "", /^text\/html/);
    assert.match(page.headers.get("content-security-policy") ?? "", /default-src 'none'/);
    assert.ok(!html.includes("<i>roundup</i>") && html.includes("Weekly &#60;i&#62;roundup&#60;/i&#62;"), "list names are escaped");
    assert.ok(!html.includes("<b>"), "the site name is escaped");
    assert.ok(!html.includes("display:none"), "an unsafe theme value falls back to the default");
    assert.match(html, /#aa3300/);
  }
  {
    const { calls, options } = harness({ statusCode: 410, body: { status: "expired" } });
    const page = await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?t=v1.abc.def"), options);
    assert.equal(page.status, 410);
    assert.match(await page.text(), /expired or was already used[\s\S]*href="\/"/);
    assert.equal(calls.length, 1);
    const bad = await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?t=" + encodeURIComponent('"><script>alert(1)</script>')), options);
    assert.equal(bad.status, 410);
    assert.ok(!(await bad.text()).includes("<script>"));
    const none = await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm"), options);
    assert.equal(none.status, 410);
    assert.equal(calls.length, 1, "a malformed or missing token never reaches the function");
    const unavailable = await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?t=abc"), { ...options, invoke: async () => { throw new Error("boom"); } });
    assert.equal(unavailable.status, 502);
  }
  // The result page names the lists from the site's own settings and ignores unknown ids.
  {
    const { calls, options } = harness();
    const page = await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?done=1&l=weekly,nope,alerts-x"), options);
    const html = await page.text();
    assert.equal(page.status, 200);
    assert.match(html, /You are subscribed/);
    assert.match(html, /Weekly &#60;i&#62;roundup&#60;\/i&#62;/);
    assert.match(html, /<li>Alerts<\/li>/);
    assert.ok(!html.includes("nope"));
    assert.equal(calls.length, 0, "the result page changes nothing and asks nothing");
  }

  // Confirm POST.
  {
    const { calls, options } = harness({ statusCode: 200, body: { status: "confirmed", lists: [{ id: "weekly", name: "Weekly" }, { id: "alerts-x", name: "Alerts" }], manageToken: "v1.manage.token" } });
    const response = await handleNewsletterConfirmPost(
      request("POST", "/api/newsletter/confirm", {
        contentType: "application/x-www-form-urlencoded",
        headers: { "cloudfront-viewer-address": "198.51.100.9:1111", "user-agent": "Mail Client/1" },
        body: "t=v1.abc.def",
      }),
      options,
    );
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), `${siteOrigin}/api/newsletter/confirm?done=1&l=weekly%2Calerts-x&m=v1.manage.token`);
    assert.equal(response.headers.get("referrer-policy"), "no-referrer");
    const done = await (await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?done=1&l=weekly&m=v1.manage.token"), harness().options)).text();
    assert.match(done, /href="\/api\/newsletter\/preferences\?t=v1.manage.token"/, "the confirmed page links to preferences");
    const noLink = await (await handleNewsletterConfirmPage(request("GET", "/api/newsletter/confirm?done=1&m=%22%3E%3Cx%3E"), harness().options)).text();
    assert.ok(!noLink.includes("preferences"), "a malformed manage token makes no link");
    assert.deepEqual(calls[0].event, { action: "confirm", token: "v1.abc.def", ip: "198.51.100.9", userAgent: "Mail Client/1" });
  }
  {
    const { calls, options } = harness({ statusCode: 410, body: { status: "expired" } });
    const post = (init: Parameters<typeof request>[2]) => handleNewsletterConfirmPost(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", ...init }), options);
    const expired = await post({ body: "t=v1.abc.def" });
    assert.equal(expired.status, 410);
    assert.match(await expired.text(), /expired/);
    assert.equal((await post({ body: "t=v1.abc.def", origin: "https://evil.example" })).status, 400);
    assert.equal((await post({ body: "t=v1.abc.def", origin: null })).status, 400);
    assert.equal((await post({ body: "t=v1.abc.def", contentType: "application/json" })).status, 415);
    assert.equal((await post({ body: "t=" + "a".repeat(5000) })).status, 413);
    assert.equal((await post({ body: "x=1" })).status, 410);
    assert.equal((await post({ body: "t=%3Cscript%3E" })).status, 410);
    assert.equal(calls.length, 1, "only the one well formed request reached the function");
    const failing = await handleNewsletterConfirmPost(request("POST", "/api/newsletter/confirm", { contentType: "application/x-www-form-urlencoded", body: "t=abc" }), {
      ...options,
      invoke: async () => { throw new Error("boom"); },
    });
    assert.equal(failing.status, 502);
  }

  // Page helpers.
  assert.equal(escapeHtml(`<a href="x">'&`), "&#60;a href=&#34;x&#34;&#62;&#39;&#38;");
  assert.equal(pageTheme(null).accent, "#1a4d8f");
  assert.equal(pageTheme({ accent: "url(javascript:x)" }).accent, "#1a4d8f");
  assert.equal(pageTheme({ accent: "#123456" }).accent, "#123456");
  const html = renderPage({
    siteName: "S", theme: pageTheme(null), heading: "<h>", paragraphs: ["<p>"], lists: ["<l>"],
    notice: "<n>", forms: [{ action: "/a", hidden: { t: '"><x>' }, checkboxes: [{ name: "l", value: '"><z>', label: "<c>", checked: true }], buttons: [{ label: "<b>", name: "action", value: "<v>" }] }],
    links: [{ href: '"><y>', label: "<a>" }],
  });
  assert.ok(!/<(h|p|l|x|b|y|a|n|z|c|v)>/.test(html.replace(/<\/?(h1|p|ul|li|a|form|button|main|title|style|html|head|body|meta|input)\b[^>]*>/g, "")), "every dynamic value is escaped");

  await manageTests();
  console.log("newsletter api ok");
})();

async function manageTests() {
  const manage = "v1.manage.token";
  const unsubscribed = { statusCode: 200, body: { status: "unsubscribed", scope: "all", lists: [{ id: "weekly", name: "Weekly <i>roundup</i>" }] } };
  const formInit = (body: string, extra: Record<string, string | null> = {}) => ({ contentType: "application/x-www-form-urlencoded", body, ...extra });

  // Disabled: 404 on both.
  {
    const { calls, options } = harness();
    for (const handler of [handleNewsletterUnsubscribe, handleNewsletterPreferences]) {
      assert.equal((await handler(request("GET", `/api/newsletter/x?t=${manage}`), { ...options, outputs: {} })).status, 404);
      assert.equal((await handler(request("POST", "/api/newsletter/x", formInit(`t=${manage}`)), { ...options, outputs: null })).status, 404);
    }
    assert.equal(calls.length, 0);
  }

  // Unsubscribe GET: a page with a POST button; nothing changes and nothing is asked of the function.
  {
    const { calls, options } = harness(unsubscribed);
    const all = await handleNewsletterUnsubscribe(request("GET", `/api/newsletter/unsubscribe?t=${manage}`), options);
    const html = await all.text();
    assert.equal(all.status, 200);
    assert.match(html, /<form class="markus-newsletter-form" method="post" action="\/api\/newsletter\/unsubscribe">/);
    assert.match(html, /name="t" value="v1.manage.token"/);
    assert.match(html, /name="page" value="1"/);
    assert.match(html, /Unsubscribe from everything/);
    assert.match(all.headers.get("content-type") ?? "", /^text\/html/);
    assert.equal(all.headers.get("cache-control"), "no-store");
    assert.match(html, /<meta name="robots" content="noindex">/);
    const one = await (await handleNewsletterUnsubscribe(request("GET", `/api/newsletter/unsubscribe?t=${manage}&l=alerts-x`), options)).text();
    assert.match(one, /name="l" value="alerts-x"/);
    assert.match(one, /Unsubscribe from this list/);
    assert.equal((await handleNewsletterUnsubscribe(request("GET", "/api/newsletter/unsubscribe"), options)).status, 400);
    assert.equal((await handleNewsletterUnsubscribe(request("GET", "/api/newsletter/unsubscribe?t=%3Cx%3E"), options)).status, 400);
    assert.equal(calls.length, 0);
  }

  // RFC 8058 one-click: a cross-origin POST (or none) with the marker and the token in the query. Tiny body, 200, idempotent.
  {
    const { calls, options } = harness(unsubscribed);
    for (const origin of [null, "https://mail.example.org", siteOrigin]) {
      const response = await handleNewsletterUnsubscribe(
        request("POST", `/api/newsletter/unsubscribe?t=${manage}&l=alerts-x`, formInit("List-Unsubscribe=One-Click", { origin })),
        options,
      );
      assert.equal(response.status, 200);
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

  // Unsubscribe POST from our page: a themed page that links to preferences.
  {
    const { calls, options } = harness(unsubscribed);
    const response = await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit(`t=${manage}&l=weekly&page=1`)), options);
    const html = await response.text();
    assert.equal(response.status, 200);
    assert.match(html, /You are unsubscribed/);
    assert.match(html, /Weekly &#60;i&#62;roundup&#60;\/i&#62;/);
    assert.match(html, /href="\/api\/newsletter\/preferences\?t=v1.manage.token"/);
    assert.deepEqual(calls[0].event, { action: "unsubscribe", token: manage, list: "weekly" });
    const invalid = await handleNewsletterUnsubscribe(request("POST", "/api/newsletter/unsubscribe", formInit("t=%22%3E&page=1")), options);
    assert.equal(invalid.status, 400);
    assert.match(await invalid.text(), /not valid/);
  }

  // Preferences GET.
  {
    const state = { statusCode: 200, body: { status: "ready", email: "r***@example.com", lists: [
      { id: "weekly", name: "Weekly <i>roundup</i>", description: "The week.", subscribed: true },
      { id: "alerts-x", name: "Alerts", description: "", subscribed: false },
    ] } };
    const { calls, options } = harness(state);
    const page = await handleNewsletterPreferences(request("GET", `/api/newsletter/preferences?t=${manage}&msg=saved`), options);
    const html = await page.text();
    assert.equal(page.status, 200);
    assert.match(html, /r\*\*\*@example.com/);
    assert.match(html, /name="l" value="weekly" checked/);
    assert.match(html, /name="l" value="alerts-x">/);
    assert.match(html, /Your preferences are saved\./);
    assert.match(html, /name="action" value="save"/);
    assert.match(html, /Unsubscribe from everything/);
    assert.match(html, /Delete my data/);
    assert.ok(!html.includes("<i>roundup</i>"), "list names are escaped");
    assert.equal(page.headers.get("cache-control"), "no-store");
    assert.deepEqual(calls[0].event, { action: "preferences_state", token: manage });
    const unknown = await handleNewsletterPreferences(request("GET", `/api/newsletter/preferences?t=${manage}&msg=<script>`), options);
    assert.ok(!(await unknown.text()).includes("<script>"));
    const invalid = await handleNewsletterPreferences(request("GET", `/api/newsletter/preferences?t=${manage}`), { ...options, invoke: async () => ({ statusCode: 400, body: { status: "invalid" } }) });
    assert.equal(invalid.status, 400);
    assert.equal((await handleNewsletterPreferences(request("GET", "/api/newsletter/preferences"), options)).status, 400);
  }

  // Preferences POST: same-origin, save / unsubscribe all / delete with a confirm step.
  {
    const saved = harness({ statusCode: 200, body: { status: "saved", lists: ["weekly"] } });
    const save = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save&l=weekly&l=alerts-x&l=BAD!`)), saved.options);
    assert.equal(save.status, 303);
    assert.equal(save.headers.get("location"), `${siteOrigin}/api/newsletter/preferences?t=${manage}&msg=saved`);
    assert.deepEqual(saved.calls[0].event, { action: "update_preferences", token: manage, lists: ["weekly", "alerts-x"] });

    const none = harness({ statusCode: 200, body: { status: "saved", lists: [] } });
    await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), none.options);
    assert.deepEqual(none.calls[0].event, { action: "update_preferences", token: manage, lists: [] }, "unticking everything saves an empty set");

    const all = harness(unsubscribed);
    const out = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=unsubscribe_all`)), all.options);
    assert.equal(out.status, 303);
    assert.match(out.headers.get("location") ?? "", /msg=unsubscribed$/);
    assert.deepEqual(all.calls[0].event, { action: "unsubscribe", token: manage });

    const deletion = harness({ statusCode: 200, body: { status: "deleted" } });
    const confirmStep = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=delete`)), deletion.options);
    const confirmHtml = await confirmStep.text();
    assert.equal(confirmStep.status, 200);
    assert.match(confirmHtml, /Delete your data\?/);
    assert.match(confirmHtml, /name="confirm" value="1"/);
    assert.equal(deletion.calls.length, 0, "nothing is deleted before the confirm step");
    const done = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=delete&confirm=1`)), deletion.options);
    assert.match(await done.text(), /Your data is deleted/);
    assert.deepEqual(deletion.calls[0].event, { action: "delete_subscriber", token: manage });

    const { calls, options } = harness(unsubscribed);
    const post = (init: ReturnType<typeof formInit>) => handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", init), options);
    assert.equal((await post(formInit(`t=${manage}&action=save`, { origin: "https://evil.example" }))).status, 400);
    assert.equal((await post(formInit(`t=${manage}&action=save`, { origin: null }))).status, 400);
    assert.equal((await post(formInit(`t=${manage}&action=save`, { contentType: "application/json" }))).status, 415);
    assert.equal((await post(formInit("t=" + manage + "&x=" + "a".repeat(5000)))).status, 413);
    assert.equal((await post(formInit(`t=${manage}&action=explode`))).status, 400);
    assert.equal((await post(formInit("action=save"))).status, 400);
    assert.equal(calls.length, 0);
    const rejected = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), { ...options, invoke: async () => ({ statusCode: 400, body: { status: "invalid" } }) });
    assert.equal(rejected.status, 400);
    const failing = await handleNewsletterPreferences(request("POST", "/api/newsletter/preferences", formInit(`t=${manage}&action=save`)), { ...options, invoke: async () => { throw new Error("boom"); } });
    assert.equal(failing.status, 502);
  }
}
