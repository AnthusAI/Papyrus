const assert = require("node:assert/strict");
const { Given, Then } = require("@cucumber/cucumber");

const DRAWER = "[data-story-announcements]";
const page = (world) => {
  assert.ok(world.page, "Expected an open browser page");
  return world.page;
};

/** The local preview's published Stories (lib/local-preview-seed.ts) and the announcements seeded for them (lib/announcements-demo.ts). */
const STORIES = {
  "harbor safety review": "preview-item-version-published-0",
  "lighthouse keepers": "preview-item-version-published-1",
  none: "preview-item-version-copywriting-0",
};

async function openStory(world, id, width, height) {
  await world.openPath(`/newsroom/articles/${id}?demo=1`, width, height);
  await page(world).waitForSelector(`${DRAWER} h3`, { state: "visible", timeout: 30_000 });
  await page(world).waitForFunction((selector) => !document.querySelector(`${selector} [data-story-announcements-loading]`), DRAWER, { timeout: 15_000 });
}

Given("I open the Story {string} in the drawer at {int} by {int}", async function (name, width, height) {
  assert.ok(STORIES[name], `no seeded Story named ${name}`);
  await openStory(this, STORIES[name], width, height);
});
Given("I open the Story with no announcements in the drawer", async function () {
  await openStory(this, STORIES.none, 1440, 1000);
});

const entry = (world, kind) => page(world).locator(`${DRAWER} [data-announcement-entry]`).filter({ has: page(world).locator(".ann-entry__head strong", { hasText: new RegExp(`^${kind}$`) }) }).first();
const lineIn = (world, channel) => world.entry.locator(`[data-delivery-line^='${channel.toLowerCase()}#']`).first();

Then("the drawer should show the Announcement {string} with {int} line(s), one for each Delivery", async function (kind, count) {
  this.entry = entry(this, kind);
  assert.equal(await this.entry.locator("[data-delivery-line]").count(), count);
});
Then("in that drawer Announcement the {string} line should read {string} with an icon", async function (channel, words) {
  const state = lineIn(this, channel).locator("[data-delivery-state-words]");
  assert.ok((await state.innerText()).includes(words), await state.innerText());
  assert.equal(await state.locator("svg").count(), 1);
});
Then("in that drawer Announcement the {string} line should say {string} with an icon", async function (channel, words) {
  const attention = lineIn(this, channel).locator("[data-attention]").filter({ hasText: words });
  assert.equal(await attention.count(), 1);
  assert.equal(await attention.locator("svg").count(), 1);
});
Then("in that drawer Announcement the {string} line should show the review {string} with an icon", async function (channel, words) {
  const review = lineIn(this, channel).locator("[data-delivery-review]");
  assert.ok((await review.innerText()).includes(words), await review.innerText());
  assert.equal(await review.locator("svg").count(), 1);
});
Then("the drawer should say {string}", async function (words) {
  assert.ok((await page(this).locator(DRAWER).innerText()).includes(words));
});
Then("the drawer should show the review flag once", async function () {
  const flags = page(this).locator(`${DRAWER} [data-review-flag]`);
  assert.equal(await flags.count(), 1);
  assert.ok((await flags.innerText()).includes("Review requested: a draft was blocked"));
});
Then("every state in the drawer should be an icon together with words", async function () {
  const bare = await page(this).evaluate((selector) => [...document.querySelectorAll(`${selector} [data-delivery-state-words], ${selector} [data-attention], ${selector} [data-delivery-review], ${selector} [data-review-flag]`)]
    .filter((node) => !node.querySelector("svg") || !(node.textContent || "").trim()).map((node) => node.outerHTML.slice(0, 120)), DRAWER);
  assert.deepEqual(bare, []);
});
Then("nothing in the drawer's announcements should have a border", async function () {
  const bordered = await page(this).evaluate((selector) => [...document.querySelectorAll(`${selector}, ${selector} *`)]
    .filter((node) => ["Top", "Right", "Bottom", "Left"].some((side) => parseFloat(getComputedStyle(node)[`border${side}Width`]) > 0 && getComputedStyle(node)[`border${side}Style`] !== "none")).length, DRAWER);
  assert.equal(bordered, 0);
});
Then("the Story page should not scroll sideways", async function () {
  assert.ok(await page(this).evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "the page scrolls sideways");
});
