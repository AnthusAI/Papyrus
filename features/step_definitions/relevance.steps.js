const assert = require("node:assert/strict");
const { Then, When } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open browser page");
  return world.page;
}

function relevanceReview(world) {
  return requirePage(world).locator("[data-reference-relevance-review]").first();
}

Then("the reference detail should show the cyclotron decision {string}", async function (summary) {
  const review = relevanceReview(this);
  await review.waitFor({ state: "visible", timeout: 10_000 });
  assert.match(await review.innerText(), new RegExp(summary.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

Then("the reference detail should say why the decision was sent to review", async function () {
  assert.match(await relevanceReview(this).innerText(), /Why you are seeing this: /);
});

Then("the reference detail should offer thumbs for {string} and {string}", async function (yes, no) {
  const review = relevanceReview(this);
  await review.getByRole("button", { name: `Yes: ${yes}` }).waitFor({ state: "visible" });
  await review.getByRole("button", { name: `No: ${no}` }).waitFor({ state: "visible" });
});

When("I give the decision a thumbs down", async function () {
  await relevanceReview(this).getByRole("button", { name: /^No: / }).click();
});

Then("the review cannot be submitted without a reason", async function () {
  assert.equal(await relevanceReview(this).getByRole("button", { name: "Submit review" }).isDisabled(), true);
});

When("I choose the reason {string} and explain {string}", async function (reason, explanation) {
  const review = relevanceReview(this);
  await review.getByLabel("Reason").selectOption({ label: reason });
  await review.getByLabel("Explanation (optional)").fill(explanation);
});

When("I submit the review", async function () {
  await relevanceReview(this).getByRole("button", { name: "Submit review" }).click();
});

Then("the reference detail should show the status {string}", async function (status) {
  const page = requirePage(this);
  await page.waitForFunction(
    (expected) => document.querySelector("[data-news-desk-reference-detail]")?.textContent?.includes(expected),
    status,
    { timeout: 10_000 },
  );
});

When("I choose the {string} references filter", async function (label) {
  await requirePage(this).getByRole("tab", { name: new RegExp(`^${label}`) }).click();
});

Then("the references list should show only {string}", async function (lineageId) {
  const ids = await requirePage(this).locator("[data-newsroom-card-id]").evaluateAll(
    (cards) => cards.map((card) => card.getAttribute("data-newsroom-card-id")),
  );
  assert.deepEqual(ids, [lineageId]);
});

Then("that reference row should be marked {string}", async function (mark) {
  assert.match(await requirePage(this).locator("[data-reference-relevance-row]").first().innerText(), new RegExp(mark));
});

Then("the reference detail should not show a relevance review", async function () {
  assert.equal(await requirePage(this).locator("[data-reference-relevance-review]").count(), 0);
});
