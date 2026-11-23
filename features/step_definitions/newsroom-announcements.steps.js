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
  await page(this).waitForSelector(`${PANEL} [data-announcements-list]`, { state: "visible", timeout: 30_000 });
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

/** The Announcement of a kind about a Story (the list names the Stories each is about); later steps speak of "it". */
const entryOf = (world, kind, title) => page(world).locator("[data-announcement-entry]").filter({ has: page(world).locator(".ann-entry__head strong", { hasText: new RegExp(`^${kind}$`) }) }).filter({ hasText: title }).first();
const lineOf = (world, channel) => world.entry.locator(`[data-delivery-line^='${channel.toLowerCase()}#']`).first();

Then("the {string} announcement about {string} should have {int} line(s), one for each Delivery", async function (kind, title, count) {
  this.entry = entryOf(this, kind, title);
  assert.equal(await this.entry.locator("[data-delivery-line]").count(), count);
});
Then("in it the {string} line should read {string} with an icon", async function (channel, words) {
  const state = lineOf(this, channel).locator("[data-delivery-state-words]");
  assert.ok((await state.innerText()).includes(words), await state.innerText());
  assert.equal(await state.locator("svg").count(), 1, "the state has an icon beside its words");
});
Then("in it the {string} line should say {string} with an icon", async function (channel, words) {
  const line = lineOf(this, channel);
  const attention = line.locator("[data-attention]").filter({ hasText: words });
  assert.equal(await attention.count(), 1, await line.innerText());
  assert.equal(await attention.locator("svg").count(), 1, "the warning has an icon beside its words");
});
Then("in it the {string} line should show the review {string} with an icon", async function (channel, words) {
  const review = lineOf(this, channel).locator("[data-delivery-review]");
  assert.ok((await review.innerText()).includes(words), await review.innerText());
  assert.equal(await review.locator("svg").count(), 1);
});
Then("the announcement should show the review flag once", async function () {
  const flags = this.entry.locator("[data-review-flag]");
  assert.equal(await flags.count(), 1);
  assert.ok((await flags.innerText()).includes("Review requested: a draft was blocked"));
  assert.equal(await flags.locator("svg").count(), 1);
});
Then("the overdue section should hold an {string} line", async function (channel) {
  const overdue = page(this).locator("[data-announcements-overdue]");
  await overdue.waitFor({ state: "visible" });
  assert.ok((await overdue.locator(`[data-delivery-line^='${channel.toLowerCase()}#']`).count()) >= 1);
  assert.ok((await overdue.locator("[data-attention='overdue']").first().innerText()).includes("Overdue"));
});
Then("the page should say that a Delivery has an attempt with no answer yet", async function () {
  assert.ok((await page(this).locator("[data-announcements-unknown]").innerText()).includes("Outcome unknown"));
});
Then("every state on the list should be an icon together with words", async function () {
  const bare = await page(this).evaluate(() => [...document.querySelectorAll("[data-delivery-state-words], [data-attention], [data-delivery-review]")]
    .filter((node) => !node.querySelector("svg") || !(node.textContent || "").trim().replace(/\s+/g, "")).map((node) => node.outerHTML.slice(0, 120)));
  assert.deepEqual(bare, []);
});
Then("nothing on the list should have a border", async function () {
  const bordered = await page(this).evaluate(() => [...document.querySelectorAll("[data-announcements-list] *")]
    .filter((node) => ["Top", "Right", "Bottom", "Left"].some((side) => parseFloat(getComputedStyle(node)[`border${side}Width`]) > 0 && getComputedStyle(node)[`border${side}Style`] !== "none")).length);
  assert.equal(bordered, 0);
});
Then("the announcements page should not scroll sideways", async function () {
  const fits = await page(this).evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  assert.ok(fits, "the page scrolls sideways");
});

// The "Review and timing" card (PPY-e2829f): the review of X story posts (the agent-policy function, in the demo an in-memory stand-in) and their edit window.
Then("the review choices should be {string}", async function (list) {
  const labels = await page(this).locator("[data-announcements-review] strong").allInnerTexts();
  assert.equal(labels.join(", "), list);
});
Then("the review {string} should be selected with the word Selected", async function (label) {
  const choice = page(this).locator("[data-announcements-review] [role=radio][aria-checked=true]");
  await choice.waitFor({ state: "visible", timeout: 10_000 });
  const found = await choice.innerText();
  assert.ok(found.includes(label) && found.includes("Selected"), found);
});
Then("the current review should say {string}", async function (words) {
  await page(this).waitForFunction((wanted) => document.querySelector("[data-announcements-review-current]").innerText.includes(wanted), words, { timeout: 10_000 });
});
When("I choose the review {string} and save the review and timing", async function (label) {
  await page(this).locator("[data-announcements-review] [role=radio]").filter({ hasText: label }).first().click();
  await page(this).locator("[data-announcements-review-save]").click();
  await page(this).locator("[data-announcements-message]").waitFor({ state: "visible", timeout: 10_000 });
});
const setTiming = async (world, window, lead) => {
  await page(world).locator("[data-announcements-window]").fill(String(window));
  await page(world).locator("[data-announcements-lock-lead]").fill(String(lead));
};
When("I set X story posts to post {int} minutes after the draft with a {int} minute lock", async function (window, lead) {
  await setTiming(this, window, lead);
});
When("I set X story posts to post {int} minutes after the draft with a {int} minute lock and save the review and timing", async function (window, lead) {
  await setTiming(this, window, lead);
  await page(this).locator("[data-announcements-review-save]").click();
  await page(this).locator("[data-announcements-message]").waitFor({ state: "visible", timeout: 10_000 });
});
Then("the timing explanation should say {string}", async function (words) {
  assert.ok((await page(this).locator("[data-announcements-timing-explain]").innerText()).includes(words));
});
Then("the timing fields should read {int} and {int}", async function (window, lead) {
  assert.equal(await page(this).locator("[data-announcements-window]").inputValue(), String(window));
  assert.equal(await page(this).locator("[data-announcements-lock-lead]").inputValue(), String(lead));
});
Then("the timing problem should say {string}", async function (words) {
  const problem = page(this).locator("[data-announcements-timing-problem]");
  assert.equal(await problem.getAttribute("role"), "alert");
  assert.ok((await problem.innerText()).includes(words), await problem.innerText());
});
Then("the review and timing save button should be disabled", async function () {
  assert.equal(await page(this).locator("[data-announcements-review-save]").isDisabled(), true);
});
Then("the timing fields should be visible", async function () {
  for (const selector of ["[data-announcements-window]", "[data-announcements-lock-lead]", "[data-announcements-review-save]"]) {
    const box = await page(this).locator(selector).boundingBox();
    const width = await page(this).evaluate(() => document.documentElement.clientWidth);
    assert.ok(box && box.x >= 0 && box.x + box.width <= width + 1, `${selector} is inside the page: ${JSON.stringify(box)} of ${width}`);
  }
});
