const assert = require("node:assert/strict");
const { Given, Then, When } = require("@cucumber/cucumber");

const PANEL = "[data-news-desk-admin-panel='newsletter']";

function requirePage(world) {
  assert.ok(world.page, "Expected an open browser page");
  return world.page;
}

function issue(world, subject) {
  return requirePage(world).locator("[data-newsletter-issue]").filter({ hasText: subject }).first();
}

Given("I open the newsletter newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/administration/newsletter?demo=1", width, height);
  await requirePage(this).waitForSelector(`${PANEL} [data-newsletter-issue]`, { state: "visible", timeout: 20_000 });
});

Then("the newsletter page should show the section {string}", async function (title) {
  await requirePage(this).locator(PANEL).getByRole("heading", { name: title, exact: true }).waitFor({ state: "visible" });
});

Then("the newsletter list {string} should read {int} confirmed", async function (name, count) {
  const text = await requirePage(this).locator("[data-newsletter-list]").filter({ hasText: name }).innerText();
  assert.ok(text.includes(String(count)), text);
});

Then("the newsletter page should say sending is paused", async function () {
  await requirePage(this).locator("[data-newsletter-paused]").waitFor({ state: "visible" });
});

Then("the newsletter page should say sending is on", async function () {
  await requirePage(this).locator("[data-newsletter-running]").waitFor({ state: "visible" });
  assert.equal(await requirePage(this).locator("[data-newsletter-paused]").count(), 0);
});

Then("the newsletter issue {string} should be {string} with a warning {string}", async function (subject, status, warning) {
  // The "edited since approval" check is a second read after the list, so wait for it.
  await requirePage(this).waitForFunction(
    ([title, word, words]) => {
      const row = [...document.querySelectorAll("[data-newsletter-issue]")].find((entry) => entry.textContent.includes(title));
      return Boolean(row) && row.querySelector("[data-newsletter-status]").textContent.includes(word) && row.textContent.includes(words);
    },
    [subject, status, warning],
    { timeout: 10_000 },
  );
});

Then("the newsletter issue {string} should be {string}", async function (subject, status) {
  await requirePage(this).waitForFunction(
    ([title, word]) => {
      const row = [...document.querySelectorAll("[data-newsletter-issue]")].find((entry) => entry.textContent.includes(title));
      return Boolean(row) && row.querySelector("[data-newsletter-status]").textContent.includes(word);
    },
    [subject, status],
    { timeout: 10_000 },
  );
});

Then("the newsletter issue {string} should link to the editor and the archive", async function (subject) {
  const row = issue(this, subject);
  assert.match(await row.locator("[data-newsletter-editor-link]").getAttribute("href"), /\/articles\/item-weekly-1225(\?|$)/);
  assert.match(await row.locator("[data-newsletter-archive-link]").getAttribute("href"), /^https:\/\/news\.example\.com\/roundup\//);
});

Then("no newsletter address should be shown outside the subscribers table", async function () {
  const outside = await requirePage(this).evaluate((selector) => {
    const panel = document.querySelector(selector);
    const clone = panel.cloneNode(true);
    for (const node of clone.querySelectorAll("[data-newsletter-subscribers], [data-newsletter-erase]")) node.remove();
    return clone.textContent;
  }, PANEL);
  assert.ok(!/@/.test(outside), "an address appears outside the subscribers table");
});

When("I preview the newsletter issue {string}", async function (subject) {
  await issue(this, subject).locator("[data-newsletter-action='preview']").click();
  await requirePage(this).locator("[data-newsletter-preview] iframe").waitFor({ state: "visible" });
});

Then("the newsletter preview should be a sandboxed frame with a plain text version", async function () {
  const frame = requirePage(this).locator("[data-newsletter-preview] iframe");
  assert.equal(await frame.getAttribute("sandbox"), "");
  assert.ok((await frame.getAttribute("srcdoc")).includes("<h1"), "the frame holds the rendered email");
  assert.ok((await requirePage(this).locator("[data-newsletter-preview] pre").innerText()).includes("A short introduction"));
});

When("I approve the newsletter issue {string} for {string}", async function (subject, when) {
  const row = issue(this, subject);
  await row.locator("[data-newsletter-action='approve']").click();
  const input = row.locator("[data-newsletter-send-at-input]");
  assert.match(await input.inputValue(), /^\d{4}-\d{2}-\d{2}T\d{2}:00$/, "the time defaults to a whole hour");
  await input.fill(when);
  await row.locator("[data-newsletter-confirm-approve]").click();
});

Then("the newsletter message should say {string}", async function (words) {
  await requirePage(this).waitForFunction(
    (expected) => document.querySelector("[data-newsletter-message]")?.textContent.includes(expected),
    words,
    { timeout: 10_000 },
  );
});

When("I ask to stop the newsletter issue {string}", async function (subject) {
  await issue(this, subject).locator("[data-newsletter-action='stop']").click();
  await requirePage(this).locator("[data-newsletter-stop]").waitFor({ state: "visible" });
});

When("I confirm stopping", async function () {
  await requirePage(this).locator("[data-newsletter-confirm-stop]").click();
});

When("I resume newsletter sending", async function () {
  await requirePage(this).locator("[data-newsletter-resume]").click();
});

When("I open the deliveries of the newsletter issue {string}", async function (subject) {
  await issue(this, subject).locator("[data-newsletter-action='deliveries']").click();
  await requirePage(this).locator("[data-newsletter-deliveries-for] table").waitFor({ state: "visible" });
});

Then("the newsletter deliveries should list a {string} and a {string} result", async function (first, second) {
  const text = await requirePage(this).locator("[data-newsletter-deliveries-for] table").innerText();
  assert.ok(text.includes(first) && text.includes(second), text);
});

Then("the newsletter deliveries should show the recent events for that issue", async function () {
  const text = await requirePage(this).locator("[data-newsletter-events]").innerText();
  assert.ok(text.includes("Bounce") && text.includes("Complaint"), text);
});

When("I enter the address {string} to erase", async function (address) {
  await requirePage(this).locator("[data-newsletter-erase-input]").fill(address);
  await requirePage(this).locator("[data-newsletter-erase-button]").click();
});

Then("the newsletter page should still list {string}", async function (address) {
  assert.ok((await requirePage(this).locator("[data-newsletter-subscribers]").innerText()).includes(address));
});

When("I confirm erasing", async function () {
  await requirePage(this).locator("[data-newsletter-confirm-erase]").click();
});

Then("the newsletter page should not list {string}", async function (address) {
  await requirePage(this).waitForFunction(
    (value) => !document.querySelector("[data-newsletter-subscribers]")?.textContent.includes(value),
    address,
    { timeout: 10_000 },
  );
});
