const assert = require("node:assert/strict");
const { Given, Then, When } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open Playwright page");
  return world.page;
}

async function openArticlesPath(world, path, width, height, readySelector) {
  await world.openPath(path, width, height);
  await requirePage(world).waitForSelector(readySelector, { state: "visible", timeout: 20_000 });
}

Given("I open the articles list at {int} by {int}", async function (width, height) {
  await openArticlesPath(this, "/newsroom/articles?demo=1", width, height, "[data-newsroom-articles-list]");
  await requirePage(this).waitForSelector("[data-newsroom-article-row]", { state: "visible", timeout: 20_000 });
});

Given("I open a new article at {int} by {int}", async function (width, height) {
  await openArticlesPath(this, "/newsroom/articles/new?demo=1", width, height, "[data-newsroom-article-editor]");
});

Given("I open the published demo article at {int} by {int}", async function (width, height) {
  await openArticlesPath(
    this,
    "/newsroom/articles/demo-article-published?demo=1",
    width,
    height,
    "[data-newsroom-article-editor]",
  );
});

Then("the articles list should show {int} articles", async function (count) {
  const rows = await requirePage(this).locator("[data-newsroom-article-row]").count();
  assert.equal(rows, count);
});

Then("the articles list should show the status badge {string}", async function (label) {
  const badges = await requirePage(this).locator("[data-newsroom-article-status]").allInnerTexts();
  assert.ok(badges.includes(label), `Expected a "${label}" badge among ${JSON.stringify(badges)}`);
});

When("I enter the article title {string}", async function (title) {
  await requirePage(this).locator("[data-newsroom-article-front-matter]").fill(`title: ${title}\n`);
});

When("I enter the article body:", async function (docString) {
  await requirePage(this).locator("[data-newsroom-article-body]").fill(docString);
});

Then("the article validation errors should include a line-numbered error", async function () {
  const page = requirePage(this);
  await page.waitForSelector("[data-newsroom-article-errors]", { state: "visible", timeout: 10_000 });
  const text = await page.locator("[data-newsroom-article-errors]").innerText();
  assert.match(text, /line \d+/);
});

Then("the article Publish button should be disabled", async function () {
  const publish = requirePage(this).locator("[data-newsroom-article-publish]");
  assert.equal(await publish.isDisabled(), true);
});

Then("the article should be reported as valid", async function () {
  await requirePage(this).waitForSelector("[data-newsroom-article-validity='valid']", {
    state: "visible",
    timeout: 10_000,
  });
});

Then("the article preview should show {string}", async function (text) {
  const preview = requirePage(this).locator("[data-newsroom-article-preview]");
  await preview.getByText(text).waitFor({ state: "visible", timeout: 10_000 });
});

When("I save the article draft", async function () {
  await requirePage(this).locator("[data-newsroom-article-save]").click();
});

When("I publish the article", async function () {
  const publish = requirePage(this).locator("[data-newsroom-article-publish]");
  await publish.click();
});

When("I unpublish the article and confirm", async function () {
  const page = requirePage(this);
  await page.locator("[data-newsroom-article-unpublish]").click();
  await page.locator("[data-newsroom-article-unpublish-confirm]").click();
});

Then("the article status should be {string}", async function (label) {
  const status = requirePage(this).locator("[data-newsroom-article-toolbar] [data-newsroom-article-status]");
  await status.filter({ hasText: new RegExp(`^${label}$`) }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the article notice should say {string}", async function (text) {
  await requirePage(this)
    .locator("[data-newsroom-article-notice]")
    .getByText(text)
    .waitFor({ state: "visible", timeout: 10_000 });
});

Then("the articles screen should not scroll horizontally", async function () {
  const overflow = await requirePage(this).evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    shell: (() => {
      const main = document.querySelector("[data-newsroom-ops-shell] main");
      return main ? main.scrollWidth - main.clientWidth : 0;
    })(),
  }));
  assert.ok(overflow.document <= 1, `Document scrolls horizontally by ${overflow.document}px`);
  assert.ok(overflow.shell <= 1, `Shell content scrolls horizontally by ${overflow.shell}px`);
});

Then("the article Edit and Preview tabs should be visible", async function () {
  const page = requirePage(this);
  await page.getByRole("tab", { name: "Edit" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.getByRole("tab", { name: "Preview" }).waitFor({ state: "visible", timeout: 10_000 });
});
