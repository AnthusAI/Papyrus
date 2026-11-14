const assert = require("node:assert/strict");
const { Then } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "Expected an open Playwright page");
  return world.page;
}

const notes = (world) => requirePage(world).locator("[data-story-trail-agent-note]");

Then("the Messages view should list {int} agent notes", async function (count) {
  await notes(this).first().waitFor({ state: "visible", timeout: 20_000 });
  assert.equal(await notes(this).count(), count);
});

Then("each agent note should be marked {string} with an icon and name its agent", async function (label) {
  const count = await notes(this).count();
  for (let index = 0; index < count; index += 1) {
    const mark = notes(this).nth(index).locator("[data-story-trail-ai-label]");
    assert.equal((await mark.textContent()).trim(), label);
    assert.equal(await mark.locator("svg").count(), 1);
    assert.ok((await notes(this).nth(index).locator("strong").first().textContent()).trim().length > 0);
  }
});

Then("the agent note from {string} should show its summary", async function (agent) {
  const note = notes(this).filter({ hasText: agent }).first();
  assert.match(await note.innerText(), /matches the paper's table 3/);
});

Then("the Messages list should be ordered newest first as {string}, {string}, {string}", async function (first, second, third) {
  const entries = requirePage(this).locator("[data-story-trail-feed] > li");
  const names = [];
  for (let index = 0; index < 3; index += 1) {
    names.push((await entries.nth(index).locator(".story-trail-row strong").first().textContent()).trim());
  }
  assert.deepEqual(names, [first, second, third]);
});

Then("the note from {string} should have no AI mark", async function (author) {
  const entry = requirePage(this).locator("[data-story-trail-feed] > li").filter({ hasText: author }).first();
  assert.equal(await entry.locator("[data-story-trail-ai-label]").count(), 0);
});

Then("each agent note should have no border or outline", async function () {
  const count = await notes(this).count();
  assert.ok(count > 0);
  for (let index = 0; index < count; index += 1) {
    const widths = await notes(this).nth(index).evaluate((node) => {
      const style = getComputedStyle(node);
      return [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth, style.outlineWidth, style.outlineStyle];
    });
    assert.deepEqual(widths.slice(0, 4), ["0px", "0px", "0px", "0px"]);
    assert.ok(widths[4] === "0px" || widths[5] === "none");
  }
});
