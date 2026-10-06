#!/usr/bin/env node
const [baseUrl, mode] = process.argv.slice(2);
if (!baseUrl || !["staging", "production"].includes(mode)) {
  console.error("usage: node scripts/check-staging-guards.mjs <base-url> <staging|production>");
  process.exit(2);
}

const failures = [];
function check(condition, message) {
  if (!condition) failures.push(message);
}

async function fetchText(pathname, options = {}) {
  const response = await fetch(new URL(pathname, baseUrl), { redirect: "manual", ...options });
  return { response, body: await response.text() };
}

const robots = await fetchText("/robots.txt");
const homepage = await fetchText("/");
const newsroom = await fetchText("/newsroom");

if (mode === "staging") {
  check(/^Disallow: \/\s*$/m.test(robots.body), "robots.txt must contain 'Disallow: /'");
  check(!/^Allow: \/\s*$/m.test(robots.body), "robots.txt must not contain 'Allow: /'");
  check(/<meta name="robots" content="noindex/.test(newsroom.body), "page must carry <meta name=\"robots\" content=\"noindex...\">");
  check(newsroom.body.includes("data-staging-banner"), "page must render the data-staging-banner element");
  check((newsroom.response.headers.get("x-robots-tag") ?? "").includes("noindex"), "responses must carry X-Robots-Tag: noindex");
  check(homepage.response.status === 307, `unauthenticated / must redirect with 307, got ${homepage.response.status}`);
  const location = homepage.response.headers.get("location") ?? "";
  check(new URL(location, baseUrl).pathname === "/newsroom", `unauthenticated / must redirect to /newsroom, got ${location || "(none)"}`);
} else {
  check(/^Allow: \/\s*$/m.test(robots.body), "robots.txt must contain 'Allow: /'");
  check(!/^Disallow: \/\s*$/m.test(robots.body), "robots.txt must not contain 'Disallow: /'");
  check(!/<meta name="robots" content="noindex/.test(newsroom.body), "page must not carry a noindex meta tag");
  check(!newsroom.body.includes("data-staging-banner"), "page must not render the staging banner");
  check(!(newsroom.response.headers.get("x-robots-tag") ?? "").includes("noindex"), "responses must not carry X-Robots-Tag: noindex");
  check(!(homepage.response.status === 307 && (homepage.response.headers.get("location") ?? "").endsWith("/newsroom")), `production / must not redirect to a gate, got ${homepage.response.status}`);
}

if (failures.length) {
  for (const failure of failures) console.error(`FAIL: ${failure}`);
  process.exit(1);
}
console.log(`staging guards ok for ${mode} at ${baseUrl}`);
