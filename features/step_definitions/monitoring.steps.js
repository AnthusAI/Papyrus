const assert = require("node:assert/strict");
const { Given, Then, When } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open browser page");
  return world.page;
}

function item(world, title) {
  return requirePage(world).locator("[data-monitoring-item]").filter({ hasText: title }).first();
}

Given("I open the monitoring newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/administration/monitoring?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-admin-panel='monitoring'] [data-monitoring-section='queue']", { state: "visible", timeout: 15_000 });
});

Then("the monitoring page should show the section {string}", async function (title) {
  const panel = requirePage(this).locator("[data-news-desk-admin-panel='monitoring']");
  await panel.getByRole("heading", { name: title }).waitFor({ state: "visible" });
});

Then("the monitoring queue should list {string} as {string}", async function (title, routing) {
  assert.match(await item(this, title).innerText(), new RegExp(routing));
});

Then("the monitoring queue should offer a link to the References entry for {string}", async function (title) {
  const href = await item(this, title).locator("[data-monitoring-reference-link]").getAttribute("href");
  assert.match(href, /\/references\/lin-1/);
});

Then("the monitoring queue should say {string} for {string}", async function (words, title) {
  assert.match(await item(this, title).innerText(), new RegExp(words));
});

Then("the monitoring usage should read {string} and {string}", async function (today, total) {
  const text = await requirePage(this).locator("[data-monitoring-section='usage']").innerText();
  assert.ok(text.includes(today) && text.includes(total), text);
});

Then("the monitoring page should not name any other publication", async function () {
  const text = await requirePage(this).locator("[data-news-desk-admin-panel='monitoring']").innerText();
  assert.ok(!text.includes("desk-b") && !text.includes("desk-c"), "another publication is named");
});

When("I choose the whole shared pipeline", async function () {
  await requirePage(this).locator("[data-monitoring-scope='all']").click();
});

Then("the monitoring queue should list the judgement for every publication", async function () {
  const text = await item(this, "Quantum paper on arXiv").innerText();
  for (const publication of ["desk-a", "desk-b", "desk-c"]) assert.ok(text.includes(publication), `${publication} missing`);
});
