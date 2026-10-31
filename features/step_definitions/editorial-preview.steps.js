const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Given, When, Then } = require("@cucumber/cucumber");

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

/** The demo backend counts what it was asked on window.__PAPYRUS_DEMO_EDITORIAL__. */
async function probe(page) {
  return page.evaluate(() => window.__PAPYRUS_DEMO_EDITORIAL__ ?? { checks: 0, versionChecks: [] });
}

const FINDINGS_COUNT = "[data-editorial-findings-count]";

Given("the editorial checks provider is down", async function () {
  await requirePage(this).evaluate(() => {
    window.__PAPYRUS_DEMO_EDITORIAL__ = { checks: 0, versionChecks: [], failNextChecks: true };
  });
});

When("I enter the article body {string}", async function (text) {
  const page = requirePage(this);
  await showTab(page, "edit");
  await page.locator("[data-newsroom-article-body]").fill(text);
});

Then("the editorial findings appear by themselves", async function () {
  // No click on Check: the panel fills a moment after the text stops changing.
  await requirePage(this).waitForFunction(
    (selector) => /\d+ open/.test(document.querySelector(selector)?.textContent ?? ""),
    FINDINGS_COUNT,
    { timeout: 15_000 },
  );
});

Then("the body editor marks {string}", async function (text) {
  const page = requirePage(this);
  await showTab(page, "edit");
  await page.waitForFunction(
    (expected) => [...document.querySelectorAll(".cm-editorial-finding")].some((node) => node.textContent === expected),
    text,
    { timeout: 15_000 },
  );
});

Then("the body editor marks {string} with the {string} severity", async function (text, severity) {
  const page = requirePage(this);
  await showTab(page, "edit");
  const marked = await page.locator(`.cm-editorial-${severity}`).evaluateAll((nodes) => nodes.map((node) => node.textContent));
  assert.ok(marked.includes(text), `Marks with severity ${severity}: ${JSON.stringify(marked)}`);
});

Then("the findings panel lists {string} as {string}", async function (policy, label) {
  const group = requirePage(this).locator(`[data-editorial-policy="${policy}"]`);
  await group.waitFor({ state: "visible", timeout: 5_000 });
  assert.match(await group.innerText(), new RegExp(label));
});

Then("the editor asked for exactly {int} check after waiting {int} seconds", async function (count, seconds) {
  const page = requirePage(this);
  await page.waitForTimeout(seconds * 1000);
  assert.equal((await probe(page)).checks, count);
});

Then("the findings panel shows the error {string}", async function (text) {
  const alert = requirePage(this).locator("[data-editorial-findings] [role=alert]");
  await alert.waitFor({ state: "visible", timeout: 15_000 });
  assert.match(await alert.innerText(), new RegExp(text));
});

Then("the server was asked to check the saved version", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => (window.__PAPYRUS_DEMO_EDITORIAL__?.versionChecks ?? []).length > 0, null, { timeout: 10_000 });
  assert.equal((await probe(page)).versionChecks.length, 1);
});

Then("I save a screenshot named {string}", async function (name) {
  const dir = process.env.EDITORIAL_SHOTS_DIR || path.join(os.tmpdir(), "editorial-shots");
  fs.mkdirSync(dir, { recursive: true });
  const page = requirePage(this);
  // Show the findings panel itself (it sits below the body), then the viewport as the editor sees it.
  await page.locator("[data-editorial-findings]").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(dir, `${name}.png`) });
});

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

const OUTLINE_FREE_REPORT = `(root) => {
  const offenders = [];
  for (const surface of document.querySelectorAll(root)) {
    for (const node of [surface, ...surface.querySelectorAll("*")]) {
      const style = getComputedStyle(node);
      const widths = ["Top", "Right", "Bottom", "Left"].map((side) => style["border" + side + "Width"]);
      if (widths.some((width) => width !== "0px") || style.outlineStyle !== "none") {
        offenders.push(node.tagName.toLowerCase() + ":" + widths.join("/") + ":" + style.outlineStyle);
      }
    }
  }
  return offenders;
}`;

async function assertOutlineFree(page, selector) {
  await page.waitForSelector(selector, { state: "visible", timeout: 15_000 });
  const offenders = await page.evaluate(`(${OUTLINE_FREE_REPORT})(${JSON.stringify(selector)})`);
  assert.deepEqual(offenders, [], `Elements with a border or an outline under ${selector}`);
}

Then("nothing in the findings panel has a border or an outline", async function () {
  await assertOutlineFree(requirePage(this), "[data-editorial-finding]");
});

Then("nothing in the findings popover has a border or an outline", async function () {
  await assertOutlineFree(requirePage(this), "[data-editorial-finding='popover']");
});

Then("every severity in the findings panel has an icon and a word", async function () {
  const severities = await requirePage(this).locator("[data-editorial-severity]").evaluateAll((nodes) =>
    nodes.map((node) => ({ icon: node.querySelector("svg") !== null, word: node.textContent.trim() })),
  );
  assert.ok(severities.length > 0, "Expected at least one severity label");
  for (const severity of severities) {
    assert.ok(severity.icon && /Must fix|Should fix|Consider/.test(severity.word), JSON.stringify(severity));
  }
});

When("I reload the page recording every console error", async function () {
  const page = requirePage(this);
  this.everyConsoleError = [];
  page.on("console", (message) => {
    if (message.type() === "error") this.everyConsoleError.push(message.text());
  });
  page.on("pageerror", (error) => this.everyConsoleError.push(error.message));
  await page.reload();
  await page.waitForSelector("[data-newsroom-article-editor]", { state: "visible", timeout: 20_000 });
  await page.waitForTimeout(3000);
});

Then("the page logged no console errors", function () {
  assert.deepEqual(this.everyConsoleError, []);
});
