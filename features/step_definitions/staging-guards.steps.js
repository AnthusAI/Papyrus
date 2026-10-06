const assert = require("node:assert/strict");
const { Given, When, Then } = require("@cucumber/cucumber");

async function fetchWithoutRedirect(world, pathname) {
  const response = await fetch(new URL(pathname, world.baseUrl), { redirect: "manual" });
  return { response, body: await response.text() };
}

Given("the site is served with SITE_ENV {string}", function (expected) {
  assert.equal(
    process.env.SITE_ENV,
    expected,
    `Start the dev server and run cucumber with SITE_ENV=${expected}.`,
  );
});

When("I request the robots file", async function () {
  this.guardRobots = (await fetchWithoutRedirect(this, "/robots.txt")).body;
});

Then("the robots file should disallow everything", function () {
  assert.match(this.guardRobots, /^Disallow: \/\s*$/m);
});

Then("the robots file should allow everything", function () {
  assert.match(this.guardRobots, /^Allow: \/\s*$/m);
  assert.doesNotMatch(this.guardRobots, /^Disallow: \/\s*$/m);
});

When("I open the newsroom as an anonymous visitor", async function () {
  this.guardPage = await fetchWithoutRedirect(this, "/newsroom");
});

Then("the page should declare noindex", function () {
  assert.match(this.guardPage.body, /<meta name="robots" content="noindex/);
  assert.match(this.guardPage.response.headers.get("x-robots-tag") ?? "", /noindex/);
});

Then("the page should not declare noindex", function () {
  assert.doesNotMatch(this.guardPage.body, /<meta name="robots" content="noindex/);
});

Then("the page should show the staging banner", function () {
  assert.ok(this.guardPage.body.includes("data-staging-banner"));
});

Then("the page should not show the staging banner", function () {
  assert.ok(!this.guardPage.body.includes("data-staging-banner"));
});

When("I request the site root without a session", async function () {
  this.guardRoot = await fetchWithoutRedirect(this, "/");
});

Then("I should be redirected to the newsroom sign-in", function () {
  assert.equal(this.guardRoot.response.status, 307);
  assert.equal(new URL(this.guardRoot.response.headers.get("location"), this.baseUrl).pathname, "/newsroom");
});
