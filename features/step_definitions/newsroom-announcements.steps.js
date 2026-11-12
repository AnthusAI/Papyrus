const assert = require("node:assert/strict");
const { Given, Then, When } = require("@cucumber/cucumber");

const PANEL = "[data-news-desk-admin-panel='announcements']";
const page = (world) => {
  assert.ok(world.page, "Expected an open browser page");
  return world.page;
};
const text = (world) => page(world).locator(PANEL).innerText();

Given("I open the announcements page at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/administration/announcements?demo=1", width, height);
  await page(this).waitForSelector(`${PANEL} [data-announcements-rows]`, { state: "visible", timeout: 30_000 });
});

Then("the announcements page should show the section {string}", async function (title) {
  await page(this).locator(PANEL).getByRole("heading", { name: title, exact: true }).waitFor({ state: "visible" });
});
Then("the setup guide should say a paid X subscription does not include API access", async function () {
  assert.match(await text(this), /a paid X subscription, the blue check, does not include this/);
});
Then("the setup guide should list {int} steps", async function (count) {
  assert.equal(await page(this).locator("[data-announcements-steps] > li").count(), count);
});
Then("the callback address should end with {string} and have a Copy button", async function (suffix) {
  assert.ok((await page(this).locator("[data-announcements-callback]").innerText()).endsWith(suffix));
  await page(this).locator("[data-announcements-copy]").waitFor({ state: "visible" });
});

When("I enter the client ID {string} and the client secret {string} and save the keys", async function (id, secret) {
  await page(this).locator("[data-announcements-client-id]").fill(id);
  await page(this).locator("[data-announcements-secret-input]").fill(secret);
  await page(this).locator("[data-announcements-save-app]").click();
  await page(this).locator("[data-announcements-secret-saved]").waitFor({ state: "visible" });
});
Then("the page should say {string}", async function (words) {
  await page(this).waitForFunction(([selector, wanted]) => document.querySelector(selector).innerText.includes(wanted), [PANEL, words], { timeout: 10_000 });
});
Then("the text {string} should not appear anywhere on the page", async function (secret) {
  const html = await page(this).content();
  assert.ok(!html.includes(secret), "the secret is in the page");
  const values = await page(this).evaluate(() => [...document.querySelectorAll("input")].map((input) => input.value));
  assert.ok(!values.includes(secret), "the secret is in a field");
});

When("I choose Connect X account", async function () {
  await page(this).locator("[data-announcements-connect]").click();
  await page(this).locator("[data-connection='connected']").waitFor({ state: "visible" });
});
When("I choose Disconnect", async function () {
  await page(this).locator("[data-announcements-disconnect]").click();
  await page(this).locator("[data-connection='not_connected']").waitFor({ state: "visible" });
});
Then("the connection should read {string}", async function (words) {
  const found = await page(this).locator("[data-announcements-connection]").innerText();
  assert.ok(found.includes(words), found);
});
Then("the permissions should include {string} and {string}", async function (first, second) {
  const facts = await page(this).locator("[data-announcements-facts]").innerText();
  assert.ok(facts.includes(first) && facts.includes(second), facts);
});
Then("the refresh health should read {string}", async function (words) {
  assert.ok((await page(this).locator("[data-announcements-facts]").innerText()).includes(words));
});
Then("the pause text should say {string}", async function (words) {
  await page(this).waitForFunction((wanted) => document.querySelector("[data-announcements-pause-text]").innerText.includes(wanted), words, { timeout: 10_000 });
});

Then("the mode {string} should be selected", async function (label) {
  const choice = page(this).locator(`[data-announcements-modes] [role=radio][aria-checked=true]`);
  assert.ok((await choice.innerText()).includes(label));
  assert.ok((await choice.innerText()).includes("Selected"));
});
When("I choose the mode {string}", async function (label) {
  await page(this).locator("[data-announcements-modes] [role=radio]").filter({ hasText: label }).first().click();
});
Then("the page should list the blocker {string}", async function (words) {
  assert.ok((await page(this).locator("[data-announcements-blockers]").innerText()).includes(words));
});
Then("the minimum rating choices should be {string}", async function (list) {
  const labels = await page(this).locator("[data-announcements-stars] strong").allInnerTexts();
  assert.equal(labels.join(", "), list);
});
Then("{string} should be selected with the word Selected", async function (label) {
  const choice = page(this).locator("[data-announcements-stars] [role=radio][aria-checked=true]");
  const found = await choice.innerText();
  assert.ok(found.includes(label) && found.includes("Selected"), found);
});

When("I choose Pause announcements", async function () {
  await page(this).locator("[data-announcements-pause-switch]").click();
  await page(this).locator("[data-paused='true']").waitFor({ state: "visible" });
});
When("I choose Resume announcements", async function () {
  await page(this).locator("[data-announcements-pause-switch]").click();
  await page(this).locator("[data-paused='false']").waitFor({ state: "visible" });
});

When("I enter the budget {int} and save the settings", async function (amount) {
  await page(this).locator("[data-announcements-budget]").fill(String(amount));
  await page(this).locator("[data-announcements-save]").click();
});
Then("the budget field should read {string}", async function (value) {
  await page(this).waitForFunction((wanted) => document.querySelector("[data-announcements-budget]").value === wanted, value, { timeout: 10_000 });
});
Then("the price table should say {string}", async function (words) {
  assert.ok((await page(this).locator("[data-announcements-prices] caption").innerText()).includes(words));
});
Then("the announcement {string} should read {string}", async function (title, state) {
  const row = page(this).locator("[data-announcement]").filter({ hasText: title }).first();
  assert.ok((await row.locator("[data-announcement-state]").innerText()).includes(state));
});
Then("the announcements page should not scroll sideways", async function () {
  const fits = await page(this).evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  assert.ok(fits, "the page scrolls sideways");
});
