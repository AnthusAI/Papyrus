const assert = require("node:assert/strict");
const { When, Then } = require("@cucumber/cucumber");

function requirePage(world) {
  assert.ok(world.page, "The browser page is not open");
  return world.page;
}

async function showTab(page, view) {
  await page.locator(`[data-newsroom-article-view="${view}"]`).click();
}

async function marked(page, selector) {
  return page.locator(selector).evaluateAll((nodes) => nodes.map((node) => node.textContent));
}

async function previewMarks(page) {
  await showTab(page, "preview");
  return marked(page, "[data-editorial-mark]");
}

async function editorMarks(page) {
  await showTab(page, "edit");
  return marked(page, ".cm-editorial-finding");
}

function popover(page) {
  return page.locator("[data-editorial-preview-popover]");
}

When("I check the article's editorial policies", async function () {
  const page = requirePage(this);
  await showTab(page, "edit");
  await page.locator("[data-editorial-check-now]").click();
  await page.waitForFunction(() => /\d+ open/.test(document.querySelector("[data-editorial-findings-count]")?.textContent ?? ""), null, {
    timeout: 10_000,
  });
});

Then("the body editor marks {string} and {string}", async function (first, second) {
  const marks = await editorMarks(requirePage(this));
  assert.ok(marks.includes(first) && marks.includes(second), `Body editor marks: ${JSON.stringify(marks)}`);
});

Then("the preview marks {string} and {string}", async function (first, second) {
  const page = requirePage(this);
  await showTab(page, "preview");
  await page.waitForSelector("[data-editorial-mark]", { timeout: 10_000 });
  const marks = await previewMarks(page);
  assert.ok(marks.includes(first) && marks.includes(second), `Preview marks: ${JSON.stringify(marks)}`);
});

When("I open the preview finding on {string}", async function (text) {
  const page = requirePage(this);
  await showTab(page, "preview");
  await page.locator("[data-editorial-mark]", { hasText: text }).first().click();
  await popover(page).waitFor({ state: "visible", timeout: 5_000 });
});

When("I ask for rewrite options in the preview", async function () {
  await popover(requirePage(this)).locator("[data-editorial-suggest]").first().click();
});

Then("the preview shows rewrite options", async function () {
  await popover(requirePage(this)).locator("[data-editorial-rewrite-option]").first().waitFor({ state: "visible", timeout: 10_000 });
});

When("I use the first rewrite option", async function () {
  await popover(requirePage(this)).locator("[data-editorial-use-option]").first().click();
});

When("I use the suggested replacement {string}", async function (replacement) {
  await popover(requirePage(this)).locator(`[data-editorial-use-replacement="${replacement}"]`).click();
});

When("I dismiss the finding", async function () {
  const box = popover(requirePage(this));
  await box.locator("[data-editorial-dismiss]").first().click();
  await box.locator("[data-editorial-confirm-dismiss]").click();
});

Then("the preview no longer marks {string}", async function (text) {
  const page = requirePage(this);
  await page.waitForFunction(
    (expected) => ![...document.querySelectorAll("[data-editorial-mark]")].some((node) => node.textContent === expected),
    text,
    { timeout: 10_000 },
  );
  assert.ok(!(await previewMarks(page)).includes(text));
});

Then("the body editor no longer marks {string}", async function (text) {
  assert.ok(!(await editorMarks(requirePage(this))).includes(text));
});

When("I select {string} on the preview", async function (text) {
  const page = requirePage(this);
  await showTab(page, "preview");
  await page.locator("[data-markus-preview]").getByText(text, { exact: false }).first().waitFor({ state: "visible", timeout: 10_000 });
  await page.evaluate((wanted) => {
    const root = document.querySelector("[data-markus-preview]");
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const at = node.textContent.indexOf(wanted);
      if (at === -1) continue;
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + wanted.length);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      node.parentElement.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return;
    }
    throw new Error(`"${wanted}" is not on the preview`);
  }, text);
  await popover(page).waitFor({ state: "visible", timeout: 5_000 });
});

When("I ask for rewrites of the preview selection", async function () {
  await popover(requirePage(this)).locator("[data-editorial-rewrite-selection]").click();
});

Then("the preview shows rewrite options for {string}", async function (sentence) {
  const box = popover(requirePage(this));
  await box.locator("[data-editorial-rewrite-option]").first().waitFor({ state: "visible", timeout: 10_000 });
  assert.match(await box.locator("[data-editorial-rewrite-target]").innerText(), new RegExp(sentence.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});
