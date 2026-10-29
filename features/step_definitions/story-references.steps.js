const assert = require("node:assert/strict");
const { Given, Then, When } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open Playwright page");
  return world.page;
}

Given("I open the demo story that is based on a Reference at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/articles/demo-article-published?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-newsroom-article-editor]", { state: "visible", timeout: 20_000 });
});

Given("I open the demo story that has no Reference at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/articles/demo-article-draft?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-newsroom-article-editor]", { state: "visible", timeout: 20_000 });
});

Given("I open the demo Reference that a story is based on at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-reference-detail]", { state: "visible", timeout: 30_000 });
});

When("I open the story's References view", async function () {
  await requirePage(this).locator('[data-newsroom-article-view="references"]').click();
  await requirePage(this).waitForSelector("[data-story-trail-view='references']", { state: "visible", timeout: 20_000 });
});

const card = (world) => requirePage(world).locator("[data-story-trail-reference-card]").first();

Then("the References view should list the Reference {string}", async function (title) {
  await card(this).waitFor({ state: "visible", timeout: 20_000 });
  assert.equal((await card(this).locator("[data-story-trail-reference-title]").innerText()).trim(), title);
});

Then("the Reference should show its site {string} and its preview image", async function (site) {
  assert.match(await card(this).locator("[data-story-trail-reference-site]").innerText(), new RegExp(site.replace(/\./g, "\\.")));
  const image = card(this).locator("[data-story-trail-reference-image]");
  assert.equal(await image.count(), 1);
  assert.equal(await image.evaluate((node) => node.complete && node.naturalWidth > 0), true);
});

Then("the Reference should be marked {string} with an icon", async function (label) {
  const role = card(this).locator('[data-story-trail-reference-role="based_on"]');
  assert.equal((await role.textContent()).trim(), label);
  assert.equal(await role.locator("svg").count(), 1);
});

Then("the References view should say that the story's text is our own", async function () {
  assert.match(await requirePage(this).locator("[data-story-trail-based-on-note]").innerText(), /text of this story is our own/);
});

Then("the Reference should offer a link that opens it", async function () {
  const link = card(this).locator("[data-story-trail-open-reference]");
  assert.match((await link.getAttribute("href")) ?? "", /\/newsroom\/references\/reference-knowledge-corpus-demo-source-history-002/);
  assert.match(await link.innerText(), /Open the Reference/);
});

Then("the Reference card should have no border or outline", async function () {
  const widths = await card(this).evaluate((node) => {
    const style = getComputedStyle(node);
    return [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth, style.outlineWidth, style.outlineStyle];
  });
  assert.deepEqual(widths.slice(0, 4), ["0px", "0px", "0px", "0px"]);
  assert.ok(widths[4] === "0px" || widths[5] === "none", `outline ${widths[4]} ${widths[5]}`);
});

Then("the Reference view should list the story {string} as {string}", async function (title, label) {
  const entry = requirePage(this).locator("[data-reference-story]").first();
  await entry.waitFor({ state: "visible", timeout: 20_000 });
  assert.match(await entry.innerText(), new RegExp(title));
  assert.match(await entry.textContent(), new RegExp(label));
  assert.equal(await entry.locator("svg").count() >= 1, true);
});

Then("the story should link to its own page", async function () {
  const href = await requirePage(this).locator("[data-reference-story] a").first().getAttribute("href");
  assert.match(href ?? "", /\/newsroom\/articles\/demo-article-published/);
});

Then("the References view should list no Reference", async function () {
  assert.equal(await requirePage(this).locator("[data-story-trail-reference-card]").count(), 0);
});
