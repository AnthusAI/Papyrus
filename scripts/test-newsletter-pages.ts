import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import {
  handleNewsletterConfirmPage,
  handleNewsletterConfirmPost,
  handleNewsletterPreferences,
  handleNewsletterSubscribe,
  isSameSiteRequest,
  type NewsletterApiOptions,
  type NewsletterEvent,
} from "../lib/newsletter-api";
import { PAGE_HEADERS, SHELL_MARKER, SHELL_PATH, clearShellCache, loadShell, pageTheme, prepareShell, renderBody, renderPage, renderShellPage } from "../lib/newsletter-pages";

// The chrome shell, its substitution and fallback, and the same-origin rule of the newsletter form posts.
const site = "https://news.example.com";
const environment = { PAPYRUS_SITE_ORIGIN: site, SITE_ENV: "production" };
const outputs = {
  custom: {
    papyrusPlugins: { newsletter: { contract: 1, fromName: "Example", lists: [{ id: "weekly", name: "Weekly roundup", description: "", kind: "roundup" }] } },
    newsletter: { actionsFunction: "newsletter-fn" },
  },
};
const SHELL = `<!DOCTYPE html><html lang="en"><head><title>Example</title>
<link rel="canonical" href="${site}${SHELL_PATH}"><meta property="og:url" content="${site}/x/">
<meta name="robots" content="noindex, nofollow"><link rel="stylesheet" href="/css/site-theme.css">
<script src="/_plugins/app.js" defer></script></head><body><header>HEAD</header><main id="main">\n${SHELL_MARKER}\n</main><footer>FOOT</footer>
<script>window.x = 1</script></body></html>`;
const token = "v1.confirm.token";

function post(path: string, body: string, headers: Record<string, string>) {
  return new NextRequest(new URL(path, "https://localhost:3000"), { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", ...headers }, body });
}

function harness(shell: string | null | Error = SHELL, answer: (event: NewsletterEvent) => { statusCode: number; body: Record<string, unknown> } = (event) =>
    event.action === "update_preferences"
      ? { statusCode: 200, body: { status: "saved" } }
      : { statusCode: 200, body: { status: "confirmed", lists: [{ id: "weekly", name: "Weekly roundup" }], manageToken: "v1.manage.token" } }) {
  const calls: NewsletterEvent[] = [];
  const fetched: string[] = [];
  const options: NewsletterApiOptions = {
    environment,
    outputs,
    nowInSeconds: 1,
    now: () => 1_000_000,
    invoke: async (_name, event) => {
      calls.push(event);
      return answer(event);
    },
    fetchShell: async (url) => {
      fetched.push(url);
      if (shell instanceof Error) throw shell;
      return shell === null ? { status: 404, contentType: "text/html", text: "not found" } : { status: 200, contentType: "text/html; charset=utf-8", text: shell };
    },
  };
  return { calls, fetched, options };
}

(async () => {
  // isSameSiteRequest: Origin first, Referer only when there is no Origin, null never.
  const headers = (init: Record<string, string>) => new Headers(init);
  assert.equal(isSameSiteRequest(headers({ origin: site }), site), true);
  assert.equal(isSameSiteRequest(headers({ origin: "null" }), site), false);
  assert.equal(isSameSiteRequest(headers({ origin: "null", referer: `${site}/p` }), site), false, "a null origin is not rescued by a referer");
  assert.equal(isSameSiteRequest(headers({ origin: "https://evil.example", referer: `${site}/p` }), site), false);
  assert.equal(isSameSiteRequest(headers({ referer: `${site}/api/newsletter/confirm?t=x` }), site), true);
  assert.equal(isSameSiteRequest(headers({ referer: `${site}.evil.example/p` }), site), false);
  assert.equal(isSameSiteRequest(headers({ referer: "not a url" }), site), false);
  assert.equal(isSameSiteRequest(headers({}), site), false);

  // The shell template: marker kept once, scripts and canonical removed, anything else refused.
  const template = prepareShell(SHELL);
  assert.ok(template && template.includes(SHELL_MARKER) && template.includes("HEAD") && template.includes("/css/site-theme.css"));
  assert.ok(!/<script|canonical|og:url/.test(template), "no script, canonical or og:url survives");
  assert.equal(prepareShell("<html><main></main></html>"), null, "no marker");
  assert.equal(prepareShell(`<main>${SHELL_MARKER}${SHELL_MARKER}</main>`), null, "two markers");
  assert.equal(prepareShell(`<main>${SHELL_MARKER}</main>${"x".repeat(600_000)}`), null, "too large");

  // Substitution: the page lands in the main area, the title is replaced, "$" in content is not a replacement pattern.
  const base = { siteName: "Example <b>", theme: pageTheme(null) };
  const page = { ...base, heading: "Hello $& <i>", paragraphs: ["Costs $1 and $` ."], forms: [{ action: "/api/newsletter/confirm", hidden: { t: token }, buttons: [{ label: "Go", secondary: true }] }] };
  const filled = renderShellPage(template!, page);
  assert.ok(filled.includes("<header>HEAD</header>") && filled.includes("<footer>FOOT</footer>"), "header and footer stay");
  assert.ok(filled.includes("<title>Hello &#36;&amp;") === false && filled.includes("<title>Hello $&#38; &#60;i&#62; - Example &#60;b&#62;</title>"), filled.match(/<title>.*<\/title>/)?.[0]);
  assert.ok(filled.includes("Costs $1 and $` ."), "dollar patterns are literal");
  assert.ok(!filled.includes(SHELL_MARKER) && /<main id="main">\n<div class="markus-document markus-newsletter-page"/.test(filled));
  assert.ok(filled.includes('class="markus-button" data-variant="secondary"'), "buttons use the site's button class");
  assert.ok(!filled.includes("<i>"), "content is escaped");
  assert.equal(renderBody(page).includes("<style"), false, "the body carries no styles of its own");
  assert.ok(renderPage(page).includes("<style>") && renderPage(page).includes("markus-newsletter-page"), "the fallback is self-contained");

  // Page responses through the routes: the shell is used, cached for five minutes, and falls back.
  {
    clearShellCache();
    const { options, fetched } = harness();
    const first = await handleNewsletterConfirmPage(new NextRequest(`${site}/api/newsletter/confirm?t=${token}`), { ...options, invoke: async () => ({ statusCode: 200, body: { status: "ready", lists: [{ name: "Weekly roundup" }] } }) });
    const text = await first.text();
    assert.equal(first.status, 200);
    assert.ok(text.includes("<header>HEAD</header>") && text.includes("Confirm your subscription") && text.includes('name="t" value="v1.confirm.token"'));
    assert.deepEqual(fetched, [`${site}${SHELL_PATH}`]);
    assert.equal(first.headers.get("referrer-policy"), "same-origin");
    assert.equal(first.headers.get("x-robots-tag"), "noindex");
    assert.equal(first.headers.get("cache-control"), "no-store");
    assert.ok(!/script-src/.test(PAGE_HEADERS["content-security-policy"]) && PAGE_HEADERS["content-security-policy"].includes("default-src 'none'"), "no scripts are allowed");
    await handleNewsletterConfirmPage(new NextRequest(`${site}/api/newsletter/confirm?done=1`), options);
    assert.equal(fetched.length, 1, "the second page came from the cache");
    await handleNewsletterConfirmPage(new NextRequest(`${site}/api/newsletter/confirm?done=1`), { ...options, now: () => 1_000_000 + 5 * 60 * 1000 + 1 });
    assert.equal(fetched.length, 2, "after five minutes the shell is fetched again");
  }
  for (const [label, shell] of [["a missing shell", null], ["a network error", new Error("down")], ["a page without the marker", "<html><main>no marker</main></html>"]] as const) {
    clearShellCache();
    const { options, fetched } = harness(shell);
    const response = await handleNewsletterConfirmPage(new NextRequest(`${site}/api/newsletter/confirm?done=1`), options);
    const text = await response.text();
    assert.equal(response.status, 200, label);
    assert.ok(text.includes("<style>") && text.includes("You are subscribed"), `${label}: the self-contained page is sent`);
    await handleNewsletterConfirmPage(new NextRequest(`${site}/api/newsletter/confirm?done=1`), options);
    assert.equal(fetched.length, 1, `${label}: a failure is not retried at once`);
  }
  {
    clearShellCache();
    const good = harness();
    await loadShell(site, { fetchShell: good.options.fetchShell, now: () => 0 });
    const failing = harness(new Error("down"));
    const kept = await loadShell(site, { fetchShell: failing.options.fetchShell, now: () => 6 * 60 * 1000 });
    assert.ok(kept?.includes("HEAD"), "the last good shell survives a failed refresh");
    clearShellCache();
  }

  // The exact request Chrome sent on Shipped: the page said no-referrer, so Origin was the string "null".
  // It is refused with a styled 400 (the edge turns 403 and 404 into the site's 404 page) and nothing is confirmed.
  for (const route of ["confirm", "preferences"] as const) {
    clearShellCache();
    const { options, calls } = harness();
    const handler = route === "confirm" ? handleNewsletterConfirmPost : handleNewsletterPreferences;
    const body = route === "confirm" ? `t=${token}` : `t=${token}&action=save&l=weekly`;
    const path = `/api/newsletter/${route}`;
    const withNull = await handler(post(path, body, { origin: "null" }), options);
    assert.equal(withNull.status, 400);
    assert.match(await withNull.text(), /did not go through/);
    for (const refused of <Array<Record<string, string>>>[{ origin: "https://evil.example" }, { origin: "null", referer: `${site}/api/newsletter/${route}?t=${token}` }, {}, { referer: "https://evil.example/" }]) {
      const response = await handler(post(path, body, refused), options);
      assert.ok(response.status === 400 && ![403, 404].includes(response.status), JSON.stringify(refused));
    }
    assert.equal(calls.length, 0, "no refused request reached the function");
    // The page now says same-origin, so the browser sends the real Origin (and a Referer).
    const real = await handler(post(path, body, { origin: site, referer: `${site}/api/newsletter/${route}?t=${token}` }), options);
    assert.equal(real.status, 303);
    assert.equal(calls.length, 1);
    // A browser that sends no Origin but a same-site Referer is accepted too.
    const byReferer = await handler(post(path, body, { referer: `${site}/api/newsletter/${route}?t=${token}` }), options);
    assert.equal(byReferer.status, 303);
    assert.equal(calls.length, 2);
  }
  // The subscribe route shares the rule and also avoids 403.
  {
    const { options, calls } = harness(SHELL, () => ({ statusCode: 202, body: { status: "check_email" } }));
    const subscribe = (headers: Record<string, string>) =>
      handleNewsletterSubscribe(
        new NextRequest(`${site}/api/newsletter/subscribe`, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify({ email: "reader@example.com", lists: ["weekly"], renderedAt: 1, website: "" }) }),
        options,
      );
    assert.equal((await subscribe({ origin: "null" })).status, 400);
    assert.equal((await subscribe({})).status, 400);
    assert.equal((await subscribe({ origin: site })).status, 202);
    assert.equal((await subscribe({ referer: `${site}/roundup/` })).status, 202);
    assert.equal(calls.length, 2);
  }
  console.log("newsletter pages ok");
})();
