const assert = require("node:assert/strict");
const { Then, When } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open browser page");
  return world.page;
}

const youRow = (world) => requirePage(world).locator("[data-review-row='you']:visible").first();
const control = (world) => requirePage(world).locator("[data-decision-control]:visible").first();

Then("the prediction marks {string} and the bar says {string}", async function (choice, confidence) {
  const predicted = control(this).locator("[data-review-choice][data-predicted]");
  await predicted.waitFor({ state: "visible", timeout: 10_000 });
  // The side is marked on the button; the confidence is printed in the bar and on no button.
  assert.match((await predicted.innerText()).replace(/\s+/g, " ").trim(), new RegExp(`^${choice} predicted$`, "i"));
  assert.equal(await control(this).locator("[data-confidence-value]").innerText(), confidence);
});

Then("the control offers Accept and Reject", async function () {
  await youRow(this).getByRole("button", { name: "Accept", exact: true }).waitFor({ state: "visible" });
  await youRow(this).getByRole("button", { name: "Reject", exact: true }).waitFor({ state: "visible" });
});

When("I tap Reject", async function () {
  await youRow(this).getByRole("button", { name: "Reject", exact: true }).click();
});

Then("the card asks for a reason in words", async function () {
  await requirePage(this).getByText(/A reason is needed to record Reject/).waitFor({ state: "visible" });
});

When("I explain {string} and record it", async function (explanation) {
  const page = requirePage(this);
  await page.locator("[data-decision-control] [data-review-reason] textarea").first().fill(explanation);
  await page.locator("[data-review-record]").first().click();
});

Then("the prediction's marker shows the answer differs from it", async function () {
  await control(this).locator("[data-prediction-mark][data-verdict='miss'] svg").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the control should say there is no prediction", async function () {
  await control(this).locator("[data-prediction-caption]").getByText(/^no prediction$/i).waitFor({ state: "visible" });
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

Then("the {string} tab count should equal the references listed", async function (label) {
  const page = requirePage(this);
  const tab = await page.getByRole("tab", { name: new RegExp(`^${label}`) }).innerText();
  const count = Number(tab.replace(/\D+/g, " ").trim().split(" ").pop());
  assert.ok(count > 0, `Expected a non-zero "${label}" count, got "${tab}"`);
  assert.equal(await page.locator("[data-newsroom-card-id]").count(), count);
});

Then("every listed reference should show a cyclotron suggestion", async function () {
  const page = requirePage(this);
  const cards = await page.locator("[data-newsroom-card-id]").count();
  assert.equal(await page.locator("[data-reference-relevance-row]").count(), cards);
});

Then("that reference row should be marked {string}", async function (mark) {
  assert.match(await requirePage(this).locator("[data-reference-relevance-row]").first().innerText(), new RegExp(mark));
});

Then("the suggestion status strip should say {string}", async function (text) {
  const strip = requirePage(this).locator("[data-reference-cyclotron-status] [data-variant='strip']").first();
  await strip.waitFor({ state: "visible", timeout: 15_000 });
  assert.match(await strip.innerText(), new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

When("I open the suggestion details", async function () {
  await requirePage(this).getByRole("button", { name: "Suggestion details" }).click();
});

Then("the suggestion details card should be titled {string}", async function (title) {
  await requirePage(this).locator("[data-reference-cyclotron-status] [data-variant='card']")
    .getByRole("heading", { name: title }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the suggestion details card should explain {string}", async function (text) {
  const card = requirePage(this).locator("[data-reference-cyclotron-status] [data-variant='card']").first();
  assert.match(await card.innerText(), new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

When("I ask for a manual review rate of {string} for {string}", async function (rate, duration) {
  const form = requirePage(this).locator("[data-reference-review-rate-form]");
  await form.getByLabel("Manual review rate").selectOption({ label: rate });
  await form.getByLabel("How long the manual rate lasts").selectOption({ label: duration });
  await form.getByRole("button", { name: "Set manual rate" }).click();
});

Then("the review rate form should confirm the rate was saved", async function () {
  await requirePage(this).locator("[data-reference-review-rate-form] [role='status']")
    .filter({ hasText: "The new rate takes effect shortly" }).waitFor({ state: "visible", timeout: 10_000 });
});
