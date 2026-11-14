const assert = require("node:assert/strict");
const { Then, When } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open Playwright page");
  return world.page;
}

const box = (world) => requirePage(world).locator("[data-assign-research]");
const assignments = (world) => requirePage(world).locator("[data-research-assignment]");

When("I open the story's Messages view", async function () {
  await requirePage(this).locator('[data-newsroom-article-view="trail"]').click();
  await requirePage(this).waitForSelector("[data-story-trail-section='work']", { state: "visible", timeout: 20_000 });
});

When("I press Assign research with nothing written", async function () {
  await box(this).locator("[data-assign-research-send]").click();
});

When("I write the direction {string} and press Assign research", async function (direction) {
  await box(this).locator("[data-assign-research-direction]").fill(direction);
  await box(this).locator("[data-assign-research-send]").click();
  await box(this).locator("[data-assign-research-done]").waitFor({ state: "visible", timeout: 20_000 });
});

Then("the Work section should start with the Assign research box", async function () {
  const first = requirePage(this).locator("[data-story-trail-section='work'] > :nth-child(2)");
  assert.notEqual(await first.getAttribute("data-assign-research"), null);
});

Then("the box should have one text area, one button with an icon, and no dropdown", async function () {
  assert.equal(await box(this).locator("textarea").count(), 1);
  assert.equal(await box(this).locator("button").count(), 1);
  assert.equal(await box(this).locator("label").count(), 0);
  assert.equal(await box(this).locator("button svg").count() >= 1, true);
  assert.equal(await box(this).locator("select, [role='combobox'], [role='listbox']").count(), 0);
});

Then("the box should have no border or outline", async function () {
  for (const selector of ["[data-assign-research]", "[data-assign-research-direction]", "[data-assign-research-send]"]) {
    const widths = await requirePage(this).locator(selector).evaluate((node) => {
      const style = getComputedStyle(node);
      return [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth, style.outlineStyle];
    });
    assert.deepEqual(widths.slice(0, 4), ["0px", "0px", "0px", "0px"], selector);
    assert.equal(widths[4], "none", selector);
  }
});

Then("the box should say {string}", async function (text) {
  assert.equal((await box(this).locator("[data-assign-research-problem]").innerText()).trim(), text);
});

Then("no new research assignment should appear", async function () {
  assert.equal(await requirePage(this).locator("[data-research-assignment='preview-research-new']").count(), 0);
  assert.equal(await assignments(this).count(), 4);
});

Then("the box should say that the research was assigned", async function () {
  assert.match(await box(this).locator("[data-assign-research-done]").innerText(), /Research assigned/);
});

Then("the Work section should show a research assignment that is waiting, with the direction {string}", async function (direction) {
  const card = assignments(this).first();
  await card.waitFor({ state: "visible", timeout: 20_000 });
  assert.equal(await card.getAttribute("data-research-state"), "waiting");
  assert.equal((await card.locator("[data-research-direction]").innerText()).trim(), direction);
});

Then("the research assignments should be shown as waiting, running, failed and finished, each with a word and an icon", async function () {
  const expected = { waiting: /Waiting/, running: /Running/, failed: /Failed/, finished: /Finished/ };
  for (const [state, word] of Object.entries(expected)) {
    const label = requirePage(this).locator(`[data-research-state="${state}"] [data-research-state-label]`);
    assert.equal(await label.count(), 1, state);
    assert.match(await label.innerText(), word);
    assert.equal(await label.locator("svg").count(), 1, state);
  }
});

Then("the failed assignment should give its reason {string}", async function (reason) {
  assert.match(await requirePage(this).locator("[data-research-state='failed'] [data-research-failure]").innerText(), new RegExp(reason));
});

const packet = (world) => requirePage(world).locator("[data-research-state='finished'] [data-research-packet]");

Then("the finished assignment should show the packet summary and the recommended angle", async function () {
  assert.match(await packet(this).locator("[data-research-packet-summary]").innerText(), /approved the crane contract/);
  assert.match(await packet(this).innerText(), /Recommended angle/);
});

Then("its claims should link to the sources they cite", async function () {
  const links = packet(this).locator("[data-research-claims] a[data-research-source]");
  assert.equal(await links.count() >= 2, true);
  assert.match((await links.first().getAttribute("href")) ?? "", /^https:\/\/authority\.example\.org\//);
  assert.equal(await links.first().getAttribute("rel"), "noreferrer");
});

Then("the packet should list where the sources disagree and the open questions", async function () {
  assert.match(await packet(this).locator("[data-research-disagreements]").innerText(), /Delivery date/);
  assert.match(await packet(this).locator("[data-research-open-questions]").innerText(), /rail spur/);
});

Then("the packet should list {string} with a claim and its reasons", async function (heading) {
  const section = packet(this).locator("[data-research-unverified]");
  assert.match(await section.textContent(), new RegExp(heading));
  assert.equal(await section.locator("svg").count() >= 1, true);
  assert.match(await section.innerText(), /delivered late/);
  assert.match(await section.innerText(), /The source only partly supports this/);
});

Then("each unverified claim should be labelled {string}, {string}, {string} or {string} with an icon, in groups, and its reasons in plain words", async function (first, second, third, fourth) {
  const labels = await packet(this).locator("[data-research-verdict]").allInnerTexts();
  assert.deepEqual(labels.map((label) => label.trim().toLowerCase()), [first, second, third, fourth].map((label) => label.toLowerCase()));
  assert.equal(await packet(this).locator("[data-research-verdict] svg").count(), 4);
  assert.deepEqual(await packet(this).locator("[data-research-held-group]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-research-held-group"))), ["contradicted", "not_shown", "needs_check", "unchecked"]);
  const text = await packet(this).locator("[data-research-unverified]").innerText();
  assert.match(text, /Not in the cited source: Rodney/);
  assert.match(text, /Not shown by the sources this run had/i);
  assert.match(text, /does not mean they are false/);
  assert.doesNotMatch(text, /rejected/i);
});

Then("the fact check line should read {string}", async function (sentence) {
  assert.match(await packet(this).locator("[data-research-fact-check]").innerText(), new RegExp(sentence));
});

Then("the page should not scroll sideways", async function () {
  const overflow = await requirePage(this).evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.equal(overflow <= 0, true, `the page is ${overflow}px wider than the screen`);
});

Then("the finished assignment should say it read 2 of 3 sources and link the one it could not open", async function () {
  const reading = requirePage(this).locator("[data-research-state='finished'] [data-research-reading]");
  assert.match(await reading.innerText(), /Read 2 of 3 sources, 1 of them in part\. 1 could not be opened/);
  assert.equal(await reading.locator("[data-research-not-opened]").getAttribute("href"), "https://contractor.example.com/schedule");
});

Then("the claim from that source should be labelled {string}", async function (label) {
  const claim = requirePage(this).locator("[data-research-state='finished'] [data-research-claims] li", { hasText: "scheduled to start in September" });
  assert.match(await claim.locator("[data-research-snippet-only]").innerText(), new RegExp(label.replace(".", "\\.")));
});

Then("the box should explain {string}", async function (text) {
  assert.ok((await box(this).locator("[data-assign-research-explains]").innerText()).includes(text));
});
