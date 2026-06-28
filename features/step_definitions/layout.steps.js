const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const { Given, Then, When } = require("@cucumber/cucumber");

Given("I open the {string} layout scenario at {int} by {int}", async function (scenarioId, width, height) {
  const pendingPresentation = this.pendingReaderSettings?.presentation;
  if (pendingPresentation && pendingPresentation !== "newspaper") {
    await this.openPresentationScenario(scenarioId, pendingPresentation, width, height);
    return;
  }
  if (this.capabilities?.supportsNewspaper) {
    await this.openNewspaperScenario(scenarioId, width, height);
  } else {
    await this.openEditionScenario(scenarioId, width, height);
  }
});

Given("I open the front page at {int} by {int}", async function (width, height) {
  await this.openPath("/", width, height);
  await requirePage(this).waitForFunction(
    () => (
      (window.__PAPYRUS_LAYOUT__ && document.querySelector(".paper-page--active")) ||
      document.querySelector("[data-presentation-engine]")
    ),
    { timeout: 15_000 },
  );
});

Given("I open the archive page at {int} by {int}", async function (width, height) {
  await this.openPath("/archive", width, height);
  await requirePage(this).waitForSelector(".archive-grid-shell", { state: "visible", timeout: 15_000 });
});

Given("I open the settings page at {int} by {int}", async function (width, height) {
  await this.openPath("/settings", width, height);
  await requirePage(this).waitForSelector(".settings-page", { state: "visible", timeout: 15_000 });
});

Given("I open the newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk]", { state: "visible", timeout: 15_000 });
});

Given("I constrain the newsroom shell width to {int} pixels", async function (width) {
  const page = requirePage(this);
  await page.waitForSelector("[data-news-desk]", { state: "visible", timeout: 15_000 });
  await page.evaluate((targetWidth) => {
    const shell = document.querySelector(".news-desk-shell");
    if (!(shell instanceof HTMLElement)) return;
    shell.style.width = `${targetWidth}px`;
    shell.style.maxWidth = `${targetWidth}px`;
    shell.style.marginRight = "auto";
  }, width);
});

Given("I open the topics newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/topics?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-section='topics']", { state: "visible", timeout: 15_000 });
});

Given("I open the references newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/references?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-section='references']", { state: "visible", timeout: 15_000 });
});

Given("I open the concepts newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/concepts?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-section='concepts']", { state: "visible", timeout: 15_000 });
});

Given("I open the administration newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/administration?demo=1&panel=users", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-section='administration']", { state: "visible", timeout: 15_000 });
  await requirePage(this).waitForSelector("[data-news-desk-admin-panel='users']", { state: "visible", timeout: 15_000 });
});

Given("I open the assignments newsroom at {int} by {int}", async function (width, height) {
  await this.openPath("/newsroom/assignments?demo=1", width, height);
  await requirePage(this).waitForSelector("[data-news-desk-assignments]", { state: "visible", timeout: 15_000 });
});

Given("I open the {string} newsroom section at {int} by {int}", async function (sectionId, width, height) {
  assert.ok(["assignments", "concepts", "messages", "references", "topics"].includes(sectionId), `Unsupported card-grid section: ${sectionId}`);
  await this.openPath(`/newsroom/${sectionId}?demo=1`, width, height);
  await waitForNewsroomSection(requirePage(this), sectionId);
  await requirePage(this).waitForSelector("[data-newsroom-card-grid]", { state: "visible", timeout: 15_000 });
});

Given("I am a test editor reader", async function () {
  this.testEditorReader = true;
});

Given("the newsroom summary is unavailable", async function () {
  this.newsroomSummaryMock = "missing";
});

Given("the newsroom summary is delayed by {int} milliseconds", async function (delayMs) {
  this.newsroomSummaryDelayMs = delayMs;
});

Given("the newsroom uses mocked reference-curation message detail data", async function () {
  this.newsroomMessageDetailMock = "reference-curation";
});

Given("the newsroom uses mocked reference summaries with leading source URI", async function () {
  this.testEditorReader = true;
  this.newsroomReferenceSummaryPayloadMock = "dedup";
});

Given("the newsroom uses mocked extracted text payload for reference detail", async function () {
  this.testEditorReader = true;
  this.newsroomReferenceExtractedTextMock = "history-001-filtered-and-original";
});

Given("the newsroom uses mocked filtered extracted text payload for reference detail", async function () {
  this.testEditorReader = true;
  this.newsroomReferenceExtractedTextMock = "history-002-filtered-only";
});

Given("the reference quality mutation fails", async function () {
  this.newsroomQualityMutationMock = "fail";
});

Given("I open the edition path {string} at {int} by {int}", async function (routePath, width, height) {
  await this.openPath(routePath, width, height);
});

Given("I open the newsroom path {string} at {int} by {int}", async function (routePath, width, height) {
  await this.openPath(routePath, width, height);
  const page = requirePage(this);
  await page.waitForSelector("[data-news-desk-reference-detail]", { state: "visible", timeout: 20_000 });
});

Given("I open article {string} at {int} by {int}", async function (slug, width, height) {
  await this.openPath(`/articles/${slug}`, width, height);
});

When("I scroll to page {int}", async function (targetPage) {
  const page = requirePage(this);
  await page.evaluate((target) => {
    window.__PAPYRUS_SCROLL_TO_PAGE__?.(target, { immediate: true });
  }, targetPage);
  await page.waitForFunction((expectedPage) => {
    const visible = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    return visible === expectedPage;
  }, targetPage);
});

When("I open the settings page in the same browser", async function () {
  const page = requirePage(this);
  await page.goto(new URL("/settings", this.baseUrl).toString(), { waitUntil: "load" });
  await page.waitForSelector(".settings-page", { state: "visible", timeout: 15_000 });
});

When("I open the {string} layout scenario in the same browser", async function (scenarioId) {
  const page = requirePage(this);
  this.currentScenarioId = scenarioId;
  await page.goto(new URL(`/?scenario=${encodeURIComponent(scenarioId)}`, this.baseUrl).toString(), { waitUntil: "load" });
  const storedPresentation = await page.evaluate(() => {
    try {
      const stored = window.localStorage.getItem("papyrus:reader-settings");
      const parsed = stored ? JSON.parse(stored) : null;
      return parsed?.presentation ?? null;
    } catch {
      return null;
    }
  });
  const pendingPresentation = this.pendingReaderSettings?.presentation ?? storedPresentation;
  if (pendingPresentation && pendingPresentation !== "newspaper") {
    await page.waitForFunction(
      ({ expectedScenarioId, expectedPresentation }) => (
        window.__PAPYRUS_SCENARIO__ === expectedScenarioId &&
        document.querySelector("[data-presentation-engine]")?.getAttribute("data-presentation-engine") === expectedPresentation
      ),
      { expectedScenarioId: scenarioId, expectedPresentation: pendingPresentation },
      { timeout: 15_000 },
    );
    return;
  }
  await page.waitForFunction(
    (expectedScenarioId) => (
      window.__PAPYRUS_SCENARIO__ === expectedScenarioId &&
      (document.querySelector(".paper-page--active") || document.querySelector("[data-presentation-engine]"))
    ),
    scenarioId,
    { timeout: 15_000 },
  );
});

When("I reload the current page", async function () {
  const page = requirePage(this);
  await page.reload({ waitUntil: "load" });
});

When("I follow the continuation jump for article {string}", async function (articleId) {
  const page = requirePage(this);
  const jump = page.locator(`.front-story[data-article-id="${articleId}"] .jump-line a`).first();
  await jump.waitFor({ state: "visible", timeout: 10_000 });
  await jump.click();
});

When("I follow the newsroom tab for {string}", async function (label) {
  const page = requirePage(this);
  const tab = page.locator("[data-news-desk-tab]", { hasText: label }).first();
  await tab.waitFor({ state: "visible", timeout: 10_000 });
  await tab.click();
  const sectionId = getNewsroomSectionId(label);
  await waitForNewsroomSection(page, sectionId);
});

When("I follow the newsroom overview link for {string}", async function (label) {
  const page = requirePage(this);
  const link = page.locator(".news-desk-ledger-item", { hasText: label }).first();
  await link.waitFor({ state: "visible", timeout: 10_000 });
  await link.click();
  await waitForNewsroomSection(page, getNewsroomSectionId(label));
});

When("I update the first newsroom category name to {string}", async function (name) {
  const page = requirePage(this);
  const firstNameInput = page.locator(".category-steering-category-card label", { hasText: "Name" }).first().locator("input");
  if (!(await firstNameInput.isVisible())) {
    await page.locator("[data-newsroom-card]").first().click();
    await firstNameInput.waitFor({ state: "visible", timeout: 10_000 });
  }
  await firstNameInput.fill(name);
  await page.locator(".category-steering-category-card button", { hasText: "Save" }).first().click();
  await page.waitForFunction((expectedName) => {
    const card = document.querySelector(".category-steering-category-card");
    return card?.getAttribute("data-saved-display-name") === expectedName;
  }, name);
});

When("I claim assignment {string} with note {string}", async function (assignmentId, note) {
  const page = requirePage(this);
  const card = page.locator(`[data-newsroom-card][data-assignment-candidate="${assignmentId}"]`).first();
  if (await card.count()) await card.click();
  const candidate = page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator(`[data-assignment-reason="${assignmentId}"]`).fill(note);
  await page.locator(".news-desk-detail-toggle--actions").click();
  await page.locator(".newsroom-list-detail-shell__action-menu button", { hasText: "Claim" }).click();
  await page.waitForFunction((id) => {
    const row = document.querySelector(`[data-assignment-candidate="${id}"]`);
    return row?.getAttribute("data-assignment-status") === "claimed";
  }, assignmentId);
});

When("I complete assignment {string} with note {string}", async function (assignmentId, note) {
  const page = requirePage(this);
  const card = page.locator(`[data-newsroom-card][data-assignment-candidate="${assignmentId}"]`).first();
  if (await card.count()) await card.click();
  const candidate = page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator(`[data-assignment-reason="${assignmentId}"]`).fill(note);
  await page.locator(".news-desk-detail-toggle--actions").click();
  await page.locator(".newsroom-list-detail-shell__action-menu button", { hasText: "Complete" }).click();
  await page.waitForFunction((id) => {
    const row = document.querySelector(`[data-assignment-candidate="${id}"]`);
    return row?.getAttribute("data-assignment-status") === "completed";
  }, assignmentId);
});

When("I open assignment {string}", async function (assignmentId) {
  const page = requirePage(this);
  const card = page.locator(`[data-newsroom-card][data-assignment-candidate="${assignmentId}"]`).first();
  await card.waitFor({ state: "visible", timeout: 10_000 });
  await card.click();
  await page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`).waitFor({ state: "visible", timeout: 10_000 });
});

When("I open story budget candidate {string}", async function (assignmentId) {
  const page = requirePage(this);
  const candidate = page.locator(`[data-story-budget-candidate="${assignmentId}"] .news-desk-story-budget-candidate__main`).first();
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.click();
  await page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`).waitFor({ state: "visible", timeout: 10_000 });
});

When("I open reference {string}", async function (referenceId) {
  const page = requirePage(this);
  const card = page.locator(`[data-newsroom-card-id="${referenceId}"]`).first();
  await card.waitFor({ state: "visible", timeout: 10_000 });
  await card.click();
  await page.locator(`[data-news-desk-reference-detail="${referenceId}"]`).waitFor({ state: "visible", timeout: 10_000 });
});

When("I merge newsroom user {string} into {string}", async function (sourceLabel, targetLabel) {
  const page = requirePage(this);
  const sourceRow = page.locator(".news-desk-user-row", { hasText: sourceLabel }).first();
  await sourceRow.waitFor({ state: "visible", timeout: 10_000 });
  await sourceRow.locator("button", { hasText: "Merge" }).click();
  await page.locator("[data-news-desk-user-merge-panel]").waitFor({ state: "visible", timeout: 10_000 });
  const targetValue = await page.locator(".news-desk-user-row", { hasText: targetLabel }).first().getAttribute("data-news-desk-user");
  assert.ok(targetValue, `Expected target user row for ${targetLabel}`);
  await page.locator("[data-news-desk-merge-target]").selectOption(targetValue);
  await page.locator("[data-news-desk-merge-reason]").fill("Same human account");
  await page.locator("[data-news-desk-merge-confirm]").click();
});

When("I scroll to the canonical category register", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => document.querySelector(".site-shell")?.getAttribute("data-news-desk-appendix-ready") === "true");
  await page.waitForFunction(() => {
    const solvedPages = window.__PAPYRUS_LAYOUT__?.pages.length ?? 0;
    const totalPages = window.__PAPYRUS_TOTAL_PAGES__ ?? 0;
    return solvedPages > 0 && totalPages > solvedPages;
  });
  const targetPage = await page.evaluate(() => (window.__PAPYRUS_LAYOUT__?.pages.length ?? 0) + 1);
  await page.evaluate((target) => {
    window.__PAPYRUS_SCROLL_TO_PAGE__?.(target, { immediate: true });
  }, targetPage);
  await page.locator("[data-news-desk-appendix-page='register']").waitFor({ state: "visible", timeout: 10_000 });
});

When("I scroll to the appendix page for root category {string}", async function (categoryName) {
  const page = requirePage(this);
  const pageNumber = await page.evaluate((name) => {
    const register = document.querySelector("[data-news-desk-appendix-page='register']");
    const links = Array.from(register?.querySelectorAll(".news-desk-appendix__category-summary h3 a") ?? []);
    const index = links.findIndex((link) => link.textContent?.trim() === name);
    const basePageCount = window.__PAPYRUS_LAYOUT__?.pages.length ?? 0;
    return index >= 0 ? basePageCount + index + 2 : null;
  }, categoryName);
  assert.ok(pageNumber, `Expected appendix page link for ${categoryName}`);
  await page.evaluate((target) => {
    window.__PAPYRUS_SCROLL_TO_PAGE__?.(target, { immediate: true });
  }, pageNumber);
  await page.locator("[data-news-desk-appendix-page='category']", { hasText: categoryName }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the active page should be a {string} page", async function (expectedKind) {
  const report = await getActivePageReport(requirePage(this));
  assert.equal(report.kind, expectedKind);
});

Then("the active visible page should be {int}", async function (expectedPage) {
  const page = requirePage(this);
  await page.waitForFunction((targetPage) => {
    const visible = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    return visible === targetPage;
  }, expectedPage);
  const visiblePage = await page.evaluate(() => (
    window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1)
  ));
  assert.equal(visiblePage, expectedPage);
});

Then("page {int} should be materialized", async function (pageNumber) {
  const state = await requirePage(this).locator(`#page-${pageNumber}`).getAttribute("data-materialized");
  assert.equal(state, "true");
});

Then("page {int} should be a page placeholder", async function (pageNumber) {
  const state = await requirePage(this).locator(`#page-${pageNumber}`).getAttribute("data-materialized");
  assert.equal(state, "false");
  await requirePage(this).locator(`#page-${pageNumber} .paper-page-content--placeholder`).waitFor({ state: "visible", timeout: 10_000 });
});

Then("no flipbook UI classes should be rendered", async function () {
  const hasFlipbook = await requirePage(this).evaluate(() => (
    Boolean(
      document.querySelector(".flipbook-controls") ||
      document.querySelector(".flipbook-shell") ||
      document.querySelector(".paper-page--enter-next") ||
      document.querySelector(".paper-page--leave-next") ||
      document.querySelector(".paper-page--enter-previous") ||
      document.querySelector(".paper-page--leave-previous"),
    )
  ));
  assert.equal(hasFlipbook, false);
});

Then("the active content scenario should be {string}", async function (expectedScenarioId) {
  const scenarioId = await requirePage(this).evaluate(() => window.__PAPYRUS_SCENARIO__ ?? null);
  assert.equal(scenarioId, expectedScenarioId);
});

Then("the active content source should be {string}", async function (expectedSource) {
  const source = await requirePage(this).locator(".site-shell").getAttribute("data-content-source");
  assert.equal(source, expectedSource);
});

Then("the newsroom should render", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk]").waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await page.locator("[data-news-desk]").getAttribute("data-category-steering-demo"), "true");
  await page.locator("h1", { hasText: "NEWSROOM" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-section='overview']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-tab='topics']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-tab='concepts']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-tab='references']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-tab='administration']").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the active newsroom section should be {string}", async function (sectionId) {
  const page = requirePage(this);
  await waitForNewsroomSection(page, sectionId);
});

Then("the newsroom should show the knowledge overview", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-section='overview']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-feeds]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-section='messages']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-section='assignments']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-section='references']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-section='messages'] h2", { hasText: "Forum" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-section='assignments'] h2", { hasText: "Assignments" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-overview-section='references'] h2", { hasText: "References" }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the newsroom overview should show newspaper sections", async function () {
  const report = await requirePage(this).evaluate(() => {
    const expected = [
      ["messages", "/newsroom/messages"],
      ["assignments", "/newsroom/assignments"],
      ["references", "/newsroom/references"],
    ];
    return expected.map(([section, path]) => {
      const root = document.querySelector(`[data-newsroom-overview-section="${section}"]`);
      const cards = Array.from(root?.querySelectorAll("[data-newsroom-overview-section-card]") ?? []);
      const more = root?.querySelector("[data-newsroom-overview-more]");
      const moreUrl = more?.getAttribute("href") ? new URL(more.getAttribute("href"), window.location.href) : null;
      return {
        cardCount: cards.length,
        morePath: moreUrl?.pathname ?? null,
        moreSearch: moreUrl?.search ?? "",
        path,
        section,
        spans: cards.map((card) => card.getAttribute("data-newsroom-card-span")),
        title: root?.querySelector("h2")?.textContent?.trim() ?? null,
      };
    });
  });
  for (const section of report) {
    assert.equal(section.morePath, section.path, `Expected ${section.section} More link to route to its desk`);
    assert.ok(section.cardCount > 0, `Expected ${section.section} overview section to render cards`);
    assert.ok(section.cardCount <= 4, `Expected ${section.section} overview section to render up to four cards`);
    assert.equal(section.spans[0], "2x2", `Expected ${section.section} lead card to be 2x2`);
    if (section.cardCount >= 4) {
      assert.equal(section.spans[3], "2x1", `Expected ${section.section} secondary card to be 2x1`);
    }
  }
});

Then("newsroom overview section headers should follow the vertical rhythm", async function () {
  const report = await requirePage(this).evaluate(() => {
    const newsDeskPage = document.querySelector(".news-desk-page");
    const rhythm = parseFloat(getComputedStyle(newsDeskPage ?? document.documentElement).getPropertyValue("--paper-rhythm")) || 0;
    return ["messages", "assignments", "references"].map((section) => {
      const header = document.querySelector(`[data-newsroom-overview-section="${section}"] .newsroom-overview-section__header`);
      const rect = header?.getBoundingClientRect();
      return {
        section,
        height: rect?.height ?? 0,
        rows: rhythm > 0 && rect ? rect.height / rhythm : 0,
      };
    });
  });
  for (const entry of report) {
    assert.ok(entry.height > 0, `Expected ${entry.section} overview header to render`);
    assert.ok(Math.abs(entry.rows - Math.round(entry.rows)) <= 0.02, `Expected ${entry.section} overview header to align to whole rhythm rows, got ${entry.rows}`);
  }
});

Then("newsroom overview section cards should not overlap or clip", async function () {
  const report = await requirePage(this).evaluate(() => {
    const cards = Array.from(document.querySelectorAll("[data-newsroom-overview-section-card]"))
      .map((card) => {
        const rect = card.getBoundingClientRect();
        return {
          id: card.getAttribute("data-newsroom-card-id") ?? "",
          clipped: card.scrollHeight > card.clientHeight + 2 || card.scrollWidth > card.clientWidth + 2,
          rect: { bottom: rect.bottom, height: rect.height, left: rect.left, right: rect.right, top: rect.top, width: rect.width },
        };
      })
      .filter((card) => card.rect.width > 0 && card.rect.height > 0);
    const overlaps = [];
    for (let leftIndex = 0; leftIndex < cards.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < cards.length; rightIndex += 1) {
        const left = cards[leftIndex].rect;
        const right = cards[rightIndex].rect;
        const horizontal = Math.min(left.right, right.right) - Math.max(left.left, right.left);
        const vertical = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top);
        if (horizontal > 1.5 && vertical > 1.5) overlaps.push(`${cards[leftIndex].id}/${cards[rightIndex].id}`);
      }
    }
    const childOverflow = Array.from(document.querySelectorAll("[data-newsroom-overview-section-card] .newsroom-card__title, [data-newsroom-overview-section-card] .newsroom-card__body, [data-newsroom-overview-section-card] .newsroom-card__meta"))
      .filter((node) => {
        const card = node.closest("[data-newsroom-overview-section-card]");
        if (!card) return false;
        const cardRect = card.getBoundingClientRect();
        const rect = node.getBoundingClientRect();
        return rect.left < cardRect.left - 2 || rect.right > cardRect.right + 2 || rect.top < cardRect.top - 2 || rect.bottom > cardRect.bottom + 2;
      })
      .map((node) => node.textContent?.trim().slice(0, 80));
    return {
      cardCount: cards.length,
      clipped: cards.filter((card) => card.clipped).map((card) => card.id),
      childOverflow,
      overlaps,
    };
  });
  assert.ok(report.cardCount > 0, "Expected visible newsroom overview cards");
  assert.deepEqual(report.overlaps, [], `Expected overview cards not to overlap: ${report.overlaps.join(", ")}`);
  assert.deepEqual(report.clipped, [], `Expected overview cards not to clip: ${report.clipped.join(", ")}`);
  assert.deepEqual(report.childOverflow, [], `Expected overview card text to stay inside cards: ${report.childOverflow.join(", ")}`);
});

Then("the newsroom section rail should show canonical sections in rank order", async function () {
  const page = requirePage(this);
  await page.locator("[data-newsroom-section-rail]").waitFor({ state: "visible", timeout: 10_000 });
  const ids = await page.locator("[data-newsroom-section-type='canonical'][data-newsroom-section-link]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-newsroom-section-link")));
  assert.deepEqual(ids, ["news", "business", "technology", "science", "methods", "history", "opinion"]);
});

Then("the newsroom section rail should keep canonical sections after {int} milliseconds", async function (delayMs) {
  const page = requirePage(this);
  await page.waitForTimeout(delayMs);
  await page.locator("[data-newsroom-section-rail]").waitFor({ state: "visible", timeout: 10_000 });
  const ids = await page.locator("[data-newsroom-section-type='canonical'][data-newsroom-section-link]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-newsroom-section-link")));
  assert.deepEqual(ids, ["news", "business", "technology", "science", "methods", "history", "opinion"]);
});

Then("the newsroom section rail should show rotating section choices", async function () {
  const page = requirePage(this);
  const toggle = page.locator("[data-newsroom-rotating-expander-toggle]");
  await toggle.waitFor({ state: "visible", timeout: 10_000 });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
  await page.locator("[data-newsroom-rotating-expander-panel]").waitFor({ state: "visible", timeout: 10_000 });
  const options = await page.locator("[data-newsroom-rotating-option]").evaluateAll((nodes) => nodes.map((node) => ({
    label: node.textContent?.trim(),
    value: node.getAttribute("data-newsroom-rotating-option"),
  })));
  assert.ok(options.length >= 1, "Expected at least one rotating section option");
  assert.deepEqual(
    options.map((option) => option.value),
    ["world", "arts", "sports", "education", "health", "security", "law-policy", "labor"],
  );
});

Then("the newsroom rotating expander should be collapsed by default", async function () {
  const page = requirePage(this);
  const toggle = page.locator("[data-newsroom-rotating-expander-toggle]");
  await toggle.waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await toggle.getAttribute("aria-expanded"), "false");
  const hidden = await page.locator("[data-newsroom-rotating-expander-panel]").getAttribute("hidden");
  assert.notEqual(hidden, null);
});

When("I open the newsroom rotating expander", async function () {
  const page = requirePage(this);
  const toggle = page.locator("[data-newsroom-rotating-expander-toggle]");
  await toggle.waitFor({ state: "visible", timeout: 10_000 });
  await toggle.click();
});

Then("the newsroom rotating expander should be expanded", async function () {
  const page = requirePage(this);
  const toggle = page.locator("[data-newsroom-rotating-expander-toggle]");
  assert.equal(await toggle.getAttribute("aria-expanded"), "true");
  await page.locator("[data-newsroom-rotating-expander-panel]").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the newsroom section rail should occupy one wide column", async function () {
  const report = await requirePage(this).evaluate(() => {
    const overview = document.querySelector("[data-news-desk-section='overview']");
    const rail = document.querySelector("[data-newsroom-section-rail]");
    if (!overview || !rail) return null;
    const overviewStyle = getComputedStyle(overview);
    const columns = overviewStyle.gridTemplateColumns.split(" ").map((value) => Number.parseFloat(value)).filter(Number.isFinite);
    const railRect = rail.getBoundingClientRect();
    const overviewRect = overview.getBoundingClientRect();
    return {
      columnCount: columns.length,
      firstColumnWidth: columns[0] ?? 0,
      overviewRight: overviewRect.right,
      railRight: railRect.right,
      railWidth: railRect.width,
    };
  });
  assert.ok(report, "Expected section rail geometry report");
  assert.equal(report.columnCount, 6);
  assert.ok(report.railWidth >= report.firstColumnWidth * 0.75, `Expected rail ${report.railWidth} to fit one column ${report.firstColumnWidth}`);
  assert.ok(report.railWidth <= report.firstColumnWidth * 1.25, `Expected rail ${report.railWidth} to fit one column ${report.firstColumnWidth}`);
  assert.ok(Math.abs(report.overviewRight - report.railRight) <= 1, "Expected section rail to sit on the right edge of the overview grid");
});

Then("the newsroom section rail should not render", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk]").waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await page.locator("[data-newsroom-section-rail]").count(), 0);
});

Then("the deep newsroom section page should show {string}", async function (expectedTitle) {
  const page = requirePage(this);
  await page.locator("[data-newsroom-deep-section]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-deep-section-eyebrow]", { hasText: "Section" }).waitFor({ state: "visible", timeout: 10_000 });
  const title = await page.locator("[data-newsroom-deep-section-title]").innerText();
  assert.equal(title.trim(), expectedTitle);
});

Then("the deep newsroom section page should still show {string} after {int} milliseconds", async function (expectedTitle, delayMs) {
  const page = requirePage(this);
  await page.waitForTimeout(delayMs);
  await page.locator("[data-newsroom-deep-section]").waitFor({ state: "visible", timeout: 10_000 });
  const title = await page.locator("[data-newsroom-deep-section-title]").innerText();
  assert.equal(title.trim(), expectedTitle);
});

Then("the deep newsroom section page should omit operational tabs", async function () {
  const page = requirePage(this);
  await page.locator("[data-newsroom-deep-section]").waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await page.locator("[data-news-desk-tab]").count(), 0);
});

Then("the topics desk should render", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-tab='topics'][aria-current='page']").waitFor({ state: "visible", timeout: 10_000 });
  const shell = page.locator("[data-news-desk-section='topics']");
  await shell.waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await shell.getAttribute("data-detail-open"), "false");
});

Then("the references desk should show reference metadata and semantic neighbors", async function () {
  const page = requirePage(this);
  await page.locator("[data-newsroom-card-grid]").waitFor({ state: "visible", timeout: 10_000 });
  const referenceCard = page.locator("[data-newsroom-card-id='reference-knowledge-corpus-demo-source-history-001']").first();
  await referenceCard.waitFor({ state: "visible", timeout: 10_000 });
  await referenceCard.click();
  await page.locator("[data-news-desk-reference-detail='reference-knowledge-corpus-demo-source-history-001']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("text=Attachments").first().waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-neighbors]", { hasText: "classified as" }).first().waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail should render the curation cluster", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-reference-curation-cluster]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-reference-accept]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-reference-reject]").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail curation controls should share one height", async function () {
  const report = await requirePage(this).evaluate(() => {
    const selectors = [
      ["accept", "[data-news-desk-reference-accept]"],
      ["reject", "[data-news-desk-reference-reject]"],
      ["stars", ".news-desk-reference-curation-cluster__stars"],
      ["menu", "[data-news-desk-reference-actions]"],
    ];
    return selectors.map(([label, selector]) => {
      const node = document.querySelector(selector);
      const rect = node?.getBoundingClientRect();
      return { label, height: rect?.height ?? 0, visible: Boolean(rect && rect.width > 0 && rect.height > 0) };
    });
  });
  const visible = report.filter((entry) => entry.visible);
  assert.equal(visible.length, report.length, `Expected all reference curation controls to be visible: ${JSON.stringify(report)}`);
  const heights = visible.map((entry) => entry.height);
  const min = Math.min(...heights);
  const max = Math.max(...heights);
  assert.ok(max - min <= 0.75, `Expected matching control heights, found ${JSON.stringify(report)}`);
});

Then("the reference detail curation cluster should align with the top toolbar", async function () {
  const report = await requirePage(this).evaluate(() => {
    const toNumber = (value) => {
      const parsed = Number.parseFloat(value ?? "");
      return Number.isFinite(parsed) ? parsed : 0;
    };
    const rectFor = (selector) => {
      const node = document.querySelector(selector);
      const rect = node?.getBoundingClientRect();
      return rect ? { left: rect.left, right: rect.right, width: rect.width } : null;
    };
    const cluster = document.querySelector("[data-news-desk-reference-curation-cluster]");
    const clusterStyle = cluster ? window.getComputedStyle(cluster) : null;
    const headerFlow = document.querySelector("[data-news-desk-reference-detail] .news-desk-reference-detail__header-flow");
    const headerFlowStyle = headerFlow ? window.getComputedStyle(headerFlow) : null;
    const detail = document.querySelector("[data-news-desk-reference-detail]");
    const detailStyle = detail ? window.getComputedStyle(detail) : null;
    return {
      cluster: rectFor("[data-news-desk-reference-curation-cluster]"),
      toolbar: rectFor(".newsroom-list-detail-shell__detail-toolbar"),
      trailing: rectFor(".newsroom-list-detail-shell__detail-toolbar-trailing"),
      detail: rectFor("[data-news-desk-reference-detail]"),
      headerFlow: rectFor("[data-news-desk-reference-detail] .news-desk-reference-detail__header-flow"),
      headerFlowMarginTop: toNumber(headerFlowStyle?.marginTop),
      clusterPaddingTop: toNumber(clusterStyle?.paddingTop),
      rhythm: toNumber(detailStyle?.getPropertyValue("--paper-rhythm")),
    };
  });
  assert.ok(report.cluster, "Expected curation cluster rect");
  if (report.toolbar && report.trailing) {
    assert.ok(Math.abs(report.cluster.right - report.toolbar.right) <= 1, `Expected curation cluster to align to toolbar right edge: ${JSON.stringify(report)}`);
    assert.ok(report.cluster.left <= report.trailing.right, `Expected curation cluster to sit under the toolbar controls: ${JSON.stringify(report)}`);
  } else {
    assert.ok(report.detail, `Expected detail panel rect when toolbar is hidden: ${JSON.stringify(report)}`);
    assert.ok(Math.abs(report.cluster.right - report.detail.right) <= 1, `Expected curation cluster to align to detail panel right edge: ${JSON.stringify(report)}`);
  }
  const topOffset = report.headerFlowMarginTop + report.clusterPaddingTop;
  assert.ok(Math.abs(topOffset - report.rhythm) <= 0.75, `Expected curation cluster top offset to equal one rhythm row: ${JSON.stringify(report)}`);
});

Then("the reference detail should not show the lower curation selector", async function () {
  const count = await requirePage(this).locator(
    "[data-news-desk-reference-detail] .news-desk-detail-block",
    { hasText: "Reference Curation" },
  ).count();
  assert.equal(count, 0, "Expected lower Reference Curation block to be removed from detail body");
});

When("I open the reference detail curation actions", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-reference-actions]").click();
  await page.locator(".newsroom-list-detail-shell__action-menu").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail actions menu should offer {string} and {string}", async function (firstLabel, secondLabel) {
  const page = requirePage(this);
  const labels = await page.locator(".newsroom-list-detail-shell__action-menu button").evaluateAll((nodes) => (
    nodes.map((node) => node.textContent?.trim()).filter(Boolean)
  ));
  assert.ok(labels.includes(firstLabel), `Expected actions menu to include ${firstLabel}, found ${labels.join(", ")}`);
  assert.ok(labels.includes(secondLabel), `Expected actions menu to include ${secondLabel}, found ${labels.join(", ")}`);
});

Then("the reference detail actions menu should not offer {string}", async function (label) {
  const labels = await requirePage(this).locator(".newsroom-list-detail-shell__action-menu button").evaluateAll((nodes) => (
    nodes.map((node) => node.textContent?.trim()).filter(Boolean)
  ));
  assert.ok(!labels.includes(label), `Expected actions menu to exclude ${label}, found ${labels.join(", ")}`);
});

Then("the reference detail actions menu should show an icon for {string}", async function (label) {
  const hasIcon = await requirePage(this)
    .locator(".newsroom-list-detail-shell__action-menu button", { hasText: label })
    .first()
    .locator(".newsroom-list-detail-shell__action-menu-icon svg")
    .count();
  assert.ok(hasIcon > 0, `Expected actions menu item ${label} to include an icon`);
});

Then("semantic reference links should use canonical path URLs", async function () {
  const { newsDeskHrefForSemanticObject } = loadSemanticGraphModule();
  assert.equal(
    newsDeskHrefForSemanticObject("reference", "reference-knowledge-corpus-demo-source-history-001"),
    "/newsroom/references/reference-knowledge-corpus-demo-source-history-001",
  );
});

Then("the reference detail toolbar should show previous and next actions", async function () {
  const page = requirePage(this);
  const report = await page.evaluate(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell][data-news-desk-section='references']");
    const buttons = Array.from(shell?.querySelectorAll(".newsroom-list-detail-shell__detail-toolbar-trailing button") ?? []).map((button) => {
      const rect = button.getBoundingClientRect();
      return {
        ariaLabel: button.getAttribute("aria-label"),
        text: button.textContent?.trim() ?? "",
        visible: rect.width > 0 && rect.height > 0,
      };
    });
    return {
      buttons,
      detailOpen: shell?.getAttribute("data-detail-open") ?? null,
      detailMode: shell?.getAttribute("data-detail-mode") ?? null,
      canToggle: window.matchMedia("(min-width: 1158px)").matches,
    };
  });
  assert.ok(report.buttons.some((button) => button.ariaLabel === "Previous" && button.visible), `Expected visible Previous action: ${JSON.stringify(report)}`);
  assert.ok(report.buttons.some((button) => button.ariaLabel === "Next" && button.visible), `Expected visible Next action: ${JSON.stringify(report)}`);
});

Then("the reference detail toolbar previous action should be disabled", async function () {
  const disabled = await requirePage(this)
    .locator("[data-newsroom-list-detail-shell][data-news-desk-section='references'] .newsroom-list-detail-shell__detail-toolbar-trailing button[aria-label='Previous']")
    .first()
    .isDisabled();
  assert.equal(disabled, true, "Expected Previous action to be disabled");
});

Then("the reference detail toolbar previous action should be enabled", async function () {
  const disabled = await requirePage(this)
    .locator("[data-newsroom-list-detail-shell][data-news-desk-section='references'] .newsroom-list-detail-shell__detail-toolbar-trailing button[aria-label='Previous']")
    .first()
    .isDisabled();
  assert.equal(disabled, false, "Expected Previous action to be enabled");
});

Then("the reference detail toolbar next action should be enabled", async function () {
  const disabled = await requirePage(this)
    .locator("[data-newsroom-list-detail-shell][data-news-desk-section='references'] .newsroom-list-detail-shell__detail-toolbar-trailing button[aria-label='Next']")
    .first()
    .isDisabled();
  assert.equal(disabled, false, "Expected Next action to be enabled");
});

When("I open the next reference from the detail toolbar", async function () {
  const page = requirePage(this);
  const currentId = await page.locator("[data-news-desk-reference-detail]").first().getAttribute("data-news-desk-reference-detail");
  this.previousReferenceDetailId = currentId;
  await page.locator("[data-newsroom-list-detail-shell][data-news-desk-section='references'] .newsroom-list-detail-shell__detail-toolbar-trailing button[aria-label='Next']").first().click();
  await page.waitForFunction((id) => {
    const detail = document.querySelector("[data-news-desk-reference-detail]");
    return detail?.getAttribute("data-news-desk-reference-detail") !== id;
  }, currentId, { timeout: 10_000 });
  this.currentReferenceDetailId = await page.locator("[data-news-desk-reference-detail]").first().getAttribute("data-news-desk-reference-detail");
});

Then("the selected reference detail should change", async function () {
  assert.ok(this.previousReferenceDetailId, "Expected a stored previous selected reference detail id");
  assert.ok(this.currentReferenceDetailId, "Expected a stored current selected reference detail id");
  assert.notEqual(this.currentReferenceDetailId, this.previousReferenceDetailId, "Expected selected reference detail to change after Next");
});

When("I open the previous reference from the detail toolbar", async function () {
  const page = requirePage(this);
  await page.locator("[data-newsroom-list-detail-shell][data-news-desk-section='references'] .newsroom-list-detail-shell__detail-toolbar-trailing button[aria-label='Previous']").first().click();
});

Then("the selected reference detail should return to the original selection", async function () {
  assert.ok(this.previousReferenceDetailId, "Expected original reference detail id from prior selection");
  await requirePage(this).waitForFunction((expectedId) => {
    const detail = document.querySelector("[data-news-desk-reference-detail]");
    return detail?.getAttribute("data-news-desk-reference-detail") === expectedId;
  }, this.previousReferenceDetailId, { timeout: 10_000 });
});

When("I set the selected reference quality to {int} stars", async function (rating) {
  const page = requirePage(this);
  await page.locator(`[data-news-desk-reference-quality-star="${rating}"]`).click();
});

Then("the reference detail should immediately show {int} filled quality stars", async function (filledStars) {
  const page = requirePage(this);
  const cluster = page.locator("[data-news-desk-reference-curation-cluster]");
  await cluster.waitFor({ state: "visible", timeout: 10_000 });
  const actualStars = Number(await cluster.getAttribute("data-reference-quality-stars") ?? "-1");
  assert.equal(actualStars, filledStars);
});

Then("the reference detail curation status should be {string}", async function (status) {
  await requirePage(this).waitForFunction((expectedStatus) => {
    const cluster = document.querySelector("[data-news-desk-reference-curation-cluster]");
    return cluster?.getAttribute("data-reference-curation-status") === expectedStatus;
  }, status, { timeout: 10_000 });
});

Then("the reference detail should show {int} filled quality stars", async function (filledStars) {
  await requirePage(this).waitForFunction((expectedStars) => {
    const cluster = document.querySelector("[data-news-desk-reference-curation-cluster]");
    return Number(cluster?.getAttribute("data-reference-quality-stars") ?? "-1") === expectedStars;
  }, filledStars, { timeout: 10_000 });
});

Then("the reference detail quality save state should become {string}", async function (tone) {
  await requirePage(this).waitForFunction((expectedTone) => {
    const cluster = document.querySelector("[data-news-desk-reference-curation-cluster]");
    return cluster?.getAttribute("data-reference-quality-tone") === expectedTone;
  }, tone, { timeout: 10_000 });
});

Then("the reference detail quality message should mention {string}", async function (message) {
  const page = requirePage(this);
  await page.waitForFunction((expectedMessage) => {
    const state = document.querySelector("[data-reference-quality-state-message]");
    return state?.textContent?.toLowerCase().includes(String(expectedMessage).toLowerCase());
  }, message, { timeout: 10_000 });
});

When("I open the reference detail insight composer", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-reference-insight-trigger]").click();
});

When("I switch the reference detail extracted text tab to {string}", async function (tabName) {
  const normalized = String(tabName).trim().toLowerCase();
  assert.ok(["filtered", "original"].includes(normalized), `Unsupported extracted text tab: ${tabName}`);
  const page = requirePage(this);
  const tab = page
    .locator(`[data-news-desk-reference-extracted-text-tab='${normalized}']`)
    .first();
  await tab.waitFor({ state: "visible", timeout: 10_000 });
  await tab.click();
});

Then("the reference detail should render topic workflow and corpus selector", async function () {
  const page = requirePage(this);
  await page.locator("[data-reference-topic-workflow]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-reference-topic-state]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-reference-topic-input]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-reference-corpus-input]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-reference-corpus-input] select").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail insight composer should be visible", async function () {
  await requirePage(this).locator("[data-news-desk-reference-insight-form]").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail should place extracted text below metadata", async function () {
  const report = await requirePage(this).evaluate(() => {
    const metadata = document.querySelector("[data-news-desk-reference-metadata-expander]");
    const extracted = document.querySelector("[data-news-desk-reference-extracted-text-section]");
    if (!metadata || !extracted) return null;
    return {
      order: metadata.compareDocumentPosition(extracted),
    };
  });
  assert.ok(report, "Expected metadata and extracted text sections in reference detail");
  assert.equal(
    Boolean(report.order & 4),
    true,
    `Expected extracted text section to render after metadata: ${JSON.stringify(report)}`,
  );
});

Then("the reference detail should render extracted text tabs", async function () {
  const page = requirePage(this);
  const tabs = page.locator("[data-news-desk-reference-extracted-text-tabs]").first();
  await tabs.waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail extracted text active tab should be {string}", async function (expectedTab) {
  const expected = String(expectedTab).trim().toLowerCase();
  const report = await requirePage(this).evaluate(() => {
    const content = document.querySelector("[data-news-desk-reference-extracted-text-content]");
    return {
      activeTab: content?.getAttribute("data-news-desk-reference-extracted-text-active-tab") ?? null,
      hasTabs: Boolean(document.querySelector("[data-news-desk-reference-extracted-text-tabs]")),
    };
  });
  assert.equal(report.hasTabs, true, `Expected extracted text tabs to render: ${JSON.stringify(report)}`);
  assert.equal(report.activeTab, expected, `Expected extracted text active tab to be "${expected}": ${JSON.stringify(report)}`);
});

Then("the reference detail extracted text tab {string} should be visible", async function (tabName) {
  const normalized = String(tabName).trim().toLowerCase();
  const page = requirePage(this);
  await page.locator(`[data-news-desk-reference-extracted-text-tab='${normalized}']`).first().waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reference detail extracted text tab {string} should be hidden", async function (tabName) {
  const normalized = String(tabName).trim().toLowerCase();
  const count = await requirePage(this).locator(`[data-news-desk-reference-extracted-text-tab='${normalized}']`).count();
  assert.equal(count, 0, `Expected extracted text tab "${normalized}" to be hidden.`);
});

Then("the reference detail extracted text should include {string}", async function (expectedText) {
  const page = requirePage(this);
  const content = page.locator("[data-news-desk-reference-extracted-text-content]").first();
  await content.waitFor({ state: "visible", timeout: 10_000 });
  const text = (await content.textContent()) ?? "";
  assert.ok(text.includes(expectedText), `Expected extracted text content to include "${expectedText}", received: ${text}`);
});

Then("the reference detail should show extracted text empty state when both tabs are missing", async function () {
  const report = await requirePage(this).evaluate(() => {
    const state = document.querySelector("[data-news-desk-reference-extracted-text-empty-state='both-missing']");
    const tabs = document.querySelector("[data-news-desk-reference-extracted-text-tabs]");
    return {
      message: state?.textContent?.trim() ?? "",
      stateExists: Boolean(state),
      tabsExist: Boolean(tabs),
    };
  });
  assert.equal(report.stateExists, true, `Expected extracted text both-missing state block: ${JSON.stringify(report)}`);
  assert.equal(report.tabsExist, false, `Expected no extracted text tabs when both modes are missing: ${JSON.stringify(report)}`);
  assert.ok(report.message.length > 0, `Expected concise empty-state copy when extracted text is unavailable: ${JSON.stringify(report)}`);
});

Then("the reference detail source URI should be clickable", async function () {
  const page = requirePage(this);
  const link = page.locator("[data-news-desk-reference-detail] .news-desk-reference-detail__source-meta-row--uri a").first();
  await link.waitFor({ state: "visible", timeout: 10_000 });
  const href = await link.getAttribute("href");
  assert.ok(href && /^(https?|s3):\/\//.test(href), `Expected clickable Source URI href, received: ${href}`);
});

Then("the reference detail should use link-standard value typography for source URI and attachments", async function () {
  const report = await requirePage(this).evaluate(() => {
    const expectedClass = "news-desk-reference-detail__link-value";
    const source = document.querySelector("[data-news-desk-reference-source-uri-value]");
    const attachmentPaths = Array.from(
      document.querySelectorAll("[data-news-desk-reference-attachment-path]"),
    );
    return {
      attachmentCount: attachmentPaths.length,
      sourceHasClass: source?.classList.contains(expectedClass) ?? false,
      sourceValue: source?.textContent?.trim() ?? "",
      attachmentMissingClassCount: attachmentPaths.filter((node) => !node.classList.contains(expectedClass)).length,
    };
  });
  assert.equal(report.sourceHasClass, true, `Expected Source URI value to use link value class: ${JSON.stringify(report)}`);
  assert.ok(report.sourceValue.length > 0, `Expected Source URI value text: ${JSON.stringify(report)}`);
  assert.ok(report.attachmentCount > 0, `Expected attachment path rows in reference detail: ${JSON.stringify(report)}`);
  assert.equal(report.attachmentMissingClassCount, 0, `Expected all attachment paths to use link value class: ${JSON.stringify(report)}`);
});

Then("the reference detail summary should not start with source URI", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-reference-detail] .news-desk-semantic-detail__summary").first().waitFor({ state: "visible", timeout: 10_000 });
  const report = await page.evaluate(() => {
    const summary = document.querySelector("[data-news-desk-reference-detail] .news-desk-semantic-detail__summary")?.textContent?.trim() ?? "";
    const sourceUri = document.querySelector("[data-news-desk-reference-detail] .news-desk-reference-detail__source-meta-row--uri a")?.textContent?.trim() ?? "";
    return { summary, sourceUri };
  });
  assert.ok(report.summary.length > 0, "Expected non-empty reference summary text");
  assert.ok(report.sourceUri.length > 0, "Expected source URI text to be present");
  assert.equal(report.summary.startsWith(report.sourceUri), false, `Expected summary not to start with source URI, got: ${report.summary}`);
});

Then("the reference detail should not show source URI above the summary", async function () {
  const page = requirePage(this);
  const report = await page.evaluate(() => {
    const sourceUri = document.querySelector("[data-news-desk-reference-detail] .news-desk-reference-detail__source-meta-row--uri a")?.textContent?.trim() ?? "";
    const subheading = document.querySelector("[data-news-desk-reference-detail] .news-desk-semantic-detail__subheading")?.textContent?.trim() ?? "";
    return { sourceUri, subheading };
  });
  assert.ok(report.sourceUri.length > 0, "Expected source URI text to be present");
  assert.notEqual(report.subheading, report.sourceUri, "Expected source URI not to render as the reference detail subheading");
});

Then("the reference detail summary should be {string}", async function (expectedSummary) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-reference-detail] .news-desk-semantic-detail__summary").waitFor({ state: "visible", timeout: 10_000 });
  const actual = (await page.locator("[data-news-desk-reference-detail] .news-desk-semantic-detail__summary").first().textContent())?.trim() ?? "";
  assert.equal(actual, expectedSummary);
});

Then("the selected reference deep link URL should be {string}", async function (referenceId) {
  const page = requirePage(this);
  await page.waitForFunction((id) => {
    const expectedPath = `/newsroom/references/${encodeURIComponent(id)}`;
    return window.location.pathname === expectedPath;
  }, referenceId, { timeout: 10_000 });
  const pathname = await page.evaluate(() => window.location.pathname);
  assert.equal(pathname, `/newsroom/references/${encodeURIComponent(referenceId)}`);
});

Then("the current URL should match the selected reference detail", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => {
    const detailId = document.querySelector("[data-news-desk-reference-detail]")?.getAttribute("data-news-desk-reference-detail");
    return Boolean(detailId && window.location.pathname === `/newsroom/references/${encodeURIComponent(detailId)}`);
  }, { timeout: 10_000 });
});

Then("the selected reference detail should be {string}", async function (referenceId) {
  await requirePage(this)
    .locator(`[data-news-desk-reference-detail="${referenceId}"]`)
    .waitFor({ state: "visible", timeout: 10_000 });
});

Then("the concepts desk should show semantic nodes and linked objects", async function () {
  const page = requirePage(this);
  const conceptCard = page.locator("[data-news-desk-section='concepts'] [data-newsroom-card]").first();
  await conceptCard.waitFor({ state: "visible", timeout: 10_000 });
  await conceptCard.click();
  await page.locator("[data-news-desk-semantic-detail]").first().waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-neighbors]").first().waitFor({ state: "visible", timeout: 10_000 });
});

Then("the newsroom card grid should render for {string}", async function (sectionId) {
  const report = await requirePage(this).evaluate((section) => {
    const shell = document.querySelector(`[data-news-desk-section="${section}"]`);
    const grid = shell?.querySelector("[data-newsroom-card-grid]");
    const cards = Array.from(shell?.querySelectorAll("[data-newsroom-card]") ?? []);
    return {
      cardCount: cards.length,
      dataGridCount: shell?.querySelectorAll("[data-news-desk-data-grid]").length ?? 0,
      gridColumns: grid ? getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean).length : 0,
      spans: cards.map((card) => card.getAttribute("data-newsroom-card-span")),
    };
  }, sectionId);
  assert.ok(report.cardCount > 0, `Expected ${sectionId} card grid to render cards`);
  assert.equal(report.dataGridCount, 0, `Expected ${sectionId} to replace the row data grid`);
  assert.ok(report.gridColumns >= 1, `Expected ${sectionId} card grid columns`);
  assert.ok(report.spans.some((span) => span && span !== "1x1"), `Expected ${sectionId} to include promoted card spans`);
});

Then("newsroom cards should not overlap or clip", async function () {
  const report = await requirePage(this).evaluate(() => {
    const cards = Array.from(document.querySelectorAll("[data-newsroom-card]"))
      .map((card) => {
        const rect = card.getBoundingClientRect();
        return {
          id: card.getAttribute("data-newsroom-card-id") ?? "",
          clipped: card.scrollHeight > card.clientHeight + 2 || card.scrollWidth > card.clientWidth + 2,
          rect: { bottom: rect.bottom, height: rect.height, left: rect.left, right: rect.right, top: rect.top, width: rect.width },
        };
      })
      .filter((card) => card.rect.width > 0 && card.rect.height > 0);
    const overlaps = [];
    for (let leftIndex = 0; leftIndex < cards.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < cards.length; rightIndex += 1) {
        const left = cards[leftIndex].rect;
        const right = cards[rightIndex].rect;
        const horizontal = Math.min(left.right, right.right) - Math.max(left.left, right.left);
        const vertical = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top);
        if (horizontal > 1.5 && vertical > 1.5) overlaps.push(`${cards[leftIndex].id}/${cards[rightIndex].id}`);
      }
    }
    const childOverflow = Array.from(document.querySelectorAll("[data-newsroom-card] .newsroom-card__title, [data-newsroom-card] .newsroom-card__body, [data-newsroom-card] .newsroom-card__meta"))
      .filter((node) => {
        const card = node.closest("[data-newsroom-card]");
        if (!card) return false;
        const cardRect = card.getBoundingClientRect();
        const rect = node.getBoundingClientRect();
        return rect.left < cardRect.left - 2 || rect.right > cardRect.right + 2 || rect.top < cardRect.top - 2 || rect.bottom > cardRect.bottom + 2;
      })
      .map((node) => node.textContent?.trim().slice(0, 80));
    return {
      cardCount: cards.length,
      clipped: cards.filter((card) => card.clipped).map((card) => card.id),
      childOverflow,
      overlaps,
    };
  });
  assert.ok(report.cardCount > 0, "Expected visible newsroom cards");
  assert.deepEqual(report.overlaps, [], `Expected cards not to overlap: ${report.overlaps.join(", ")}`);
  assert.deepEqual(report.clipped, [], `Expected cards not to clip: ${report.clipped.join(", ")}`);
  assert.deepEqual(report.childOverflow, [], `Expected card text to stay inside cards: ${report.childOverflow.join(", ")}`);
});

When("I open the first newsroom card detail", async function () {
  const page = requirePage(this);
  const card = page.locator("[data-newsroom-card]").first();
  await card.waitFor({ state: "visible", timeout: 10_000 });
  const wasOpen = await page.evaluate(() => document.querySelector("[data-newsroom-list-detail-shell]")?.getAttribute("data-detail-open") === "true");
  await card.click();
  let animated = false;
  try {
    await page.waitForFunction(() => {
      const grid = document.querySelector("[data-newsroom-card-grid]");
      if (grid?.getAttribute("data-newsroom-card-grid-animating") === "true") return true;
      return Array.from(document.querySelectorAll("[data-newsroom-card]")).some((node) => {
        const transform = getComputedStyle(node).transform;
        return Boolean(transform && transform !== "none");
      });
    }, undefined, { timeout: 500 });
    animated = true;
  } catch {
    animated = false;
  }
  this.newsroomInitialDetailOpen = { animated, wasOpen };
  await page.waitForFunction(() => document.querySelector("[data-newsroom-list-detail-shell]")?.getAttribute("data-detail-open") === "true");
});

When("I open newsroom detail from the card list", async function () {
  const page = requirePage(this);
  const isOpen = await page.evaluate(() => document.querySelector("[data-newsroom-list-detail-shell]")?.getAttribute("data-detail-open") === "true");
  if (isOpen) return;
  const cards = page.locator("[data-newsroom-card]");
  const count = await cards.count();
  assert.ok(count > 0, "Expected at least one newsroom card to open detail");
  if (count > 1) {
    await cards.nth(1).click();
  } else {
    await cards.first().click();
  }
  await page.waitForFunction(() => document.querySelector("[data-newsroom-list-detail-shell]")?.getAttribute("data-detail-open") === "true");
});

Then("the initial newsroom detail open should not animate card resizing", async function () {
  const state = this.newsroomInitialDetailOpen;
  assert.ok(state, "Expected initial newsroom detail-open animation state");
  if (!state.wasOpen) {
    assert.equal(state.animated, false, "Expected first detail open to suppress card-level Flip animation");
  }
});

Then("the newsroom card grid should scale to the split width", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const surface = document.querySelector("[data-newsroom-card-grid-surface]");
    const scale = Number(shell?.getAttribute("data-newsroom-card-scale") ?? "1");
    if (!surface || !(scale < 0.99)) return false;
    const transform = getComputedStyle(surface).transform;
    if (!transform || transform === "none") return false;
    const values = transform.match(/matrix\(([^)]+)\)/)?.[1]?.split(",").map((value) => Number(value.trim())) ?? [];
    const matrixScale = values[0] ?? 1;
    return Math.abs(matrixScale - scale) <= 0.05;
  }, undefined, { timeout: 10_000 });
  const report = await page.evaluate(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const viewport = document.querySelector("[data-newsroom-card-grid-viewport]");
    const surface = document.querySelector("[data-newsroom-card-grid-surface]");
    const scale = Number(shell?.getAttribute("data-newsroom-card-scale") ?? "1");
    const viewportWidth = viewport?.getBoundingClientRect().width ?? 0;
    const surfaceWidth = surface?.getBoundingClientRect().width ?? 0;
    const unscaledSurfaceWidth = scale > 0 ? surfaceWidth / scale : surfaceWidth;
    const expectedScale = unscaledSurfaceWidth > 0 ? viewportWidth / unscaledSurfaceWidth : 1;
    return {
      expectedScale,
      scale,
      surfaceWidth,
      unscaledSurfaceWidth,
      viewportWidth,
    };
  });
  assert.ok(report.scale < 0.99, `Expected card grid to scale down; found ${report.scale}`);
  assert.ok(
    Math.abs(report.scale - report.expectedScale) <= 0.05,
    `Expected scale ${report.scale} to match split ratio ${report.expectedScale} (viewport ${report.viewportWidth}, surface ${report.unscaledSurfaceWidth})`,
  );
});

Then("the newsroom left pane should be scrollable in split view", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const pane = shell?.querySelector("[data-newsroom-list-pane='true']");
    if (!(pane instanceof HTMLElement)) return false;
    return shell?.getAttribute("data-detail-mode") === "split";
  }, undefined, { timeout: 10_000 });
  const report = await page.evaluate(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const pane = shell?.querySelector("[data-newsroom-list-pane='true']");
    const lede = pane?.querySelector(".news-desk-lede");
    if (!(pane instanceof HTMLElement)) return null;
    return {
      clientHeight: pane.clientHeight,
      isOverflowing: pane.scrollHeight > pane.clientHeight + 8,
      ledeTop: lede ? lede.getBoundingClientRect().top : null,
      maxHeight: getComputedStyle(pane).maxHeight,
      overflowY: getComputedStyle(pane).overflowY,
      scrollHeight: pane.scrollHeight,
      scrollTop: pane.scrollTop,
    };
  });
  assert.ok(report, "Expected newsroom left pane");
  assert.ok(report.overflowY === "auto" || report.overflowY === "scroll", `Expected scrollable left pane overflow, found ${report.overflowY}`);
  assert.notEqual(report.maxHeight, "none", "Expected left pane max-height constraint in wide split");
  this.newsroomLeftPaneBeforeScroll = report;
});

When("I scroll the newsroom left pane down", async function () {
  const page = requirePage(this);
  const report = await page.evaluate(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const pane = shell?.querySelector("[data-newsroom-list-pane='true']");
    const lede = pane?.querySelector(".news-desk-lede");
    if (!(pane instanceof HTMLElement)) return null;
    const maxScrollTop = Math.max(0, pane.scrollHeight - pane.clientHeight);
    if (maxScrollTop <= 0) {
      return {
        ledeTop: lede ? lede.getBoundingClientRect().top : null,
        scrollTop: pane.scrollTop,
        skipped: true,
      };
    }
    const targetScrollTop = Math.min(maxScrollTop, Math.max(120, Math.floor(pane.clientHeight * 0.35)));
    pane.scrollTo({ top: targetScrollTop, behavior: "auto" });
    return {
      ledeTop: lede ? lede.getBoundingClientRect().top : null,
      skipped: false,
      scrollTop: pane.scrollTop,
    };
  });
  assert.ok(report, "Expected newsroom left pane");
  this.newsroomLeftPaneAfterScroll = report;
});

Then("the newsroom section lede should move up within the left pane", async function () {
  const before = this.newsroomLeftPaneBeforeScroll;
  const after = this.newsroomLeftPaneAfterScroll;
  assert.ok(before && after, "Expected pre/post newsroom pane scroll snapshots");
  if (after.skipped || !before.isOverflowing) return;
  assert.ok(after.scrollTop > before.scrollTop + 5, `Expected left pane scrollTop to increase from ${before.scrollTop} to ${after.scrollTop}`);
  assert.notEqual(before.ledeTop, null, "Expected lede top snapshot before scroll");
  assert.notEqual(after.ledeTop, null, "Expected lede top snapshot after scroll");
  assert.ok(after.ledeTop < before.ledeTop - 5, `Expected lede to move up when pane scrolls (${before.ledeTop} -> ${after.ledeTop})`);
});

When("I select a different newsroom card", async function () {
  const page = requirePage(this);
  const before = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll("[data-newsroom-card]"));
    const active = cards.find((card) => card.getAttribute("data-active") === "true") ?? cards[0] ?? null;
    const target = cards.find((card) => card !== active) ?? null;
    const rectFor = (card) => {
      const rect = card.getBoundingClientRect();
      return {
        bottom: rect.bottom,
        height: rect.height,
        left: rect.left,
        right: rect.right,
        top: rect.top,
        width: rect.width,
      };
    };
    return {
      cards: cards.map((card) => ({
        active: card.getAttribute("data-active") === "true",
        id: card.getAttribute("data-newsroom-card-id"),
        rect: rectFor(card),
        role: card.getAttribute("data-newsroom-card-template-role"),
        span: card.getAttribute("data-newsroom-card-span"),
      })),
      activeId: active?.getAttribute("data-newsroom-card-id") ?? null,
      targetId: target?.getAttribute("data-newsroom-card-id") ?? null,
    };
  });
  assert.ok(before.targetId, "Expected a second newsroom card to select");
  await page.locator(`[data-newsroom-card-id="${before.targetId}"]`).click();
  let animated = false;
  try {
    await page.waitForFunction(() => {
      const grid = document.querySelector("[data-newsroom-card-grid]");
      if (grid?.getAttribute("data-newsroom-card-grid-animating") === "true") return true;
      return Array.from(document.querySelectorAll("[data-newsroom-card]")).some((card) => {
        const transform = getComputedStyle(card).transform;
        return Boolean(transform && transform !== "none");
      });
    }, undefined, { timeout: 1_000 });
    animated = true;
  } catch {
    animated = false;
  }
  await page.waitForFunction((targetId) => {
    const grid = document.querySelector("[data-newsroom-card-grid]");
    const target = document.querySelector(`[data-newsroom-card-id="${targetId}"]`);
    return grid?.getAttribute("data-newsroom-card-grid-animating") !== "true"
      && target?.getAttribute("data-active") === "true";
  }, before.targetId, { timeout: 5_000 });
  const after = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll("[data-newsroom-card]"));
    const rectFor = (card) => {
      const rect = card.getBoundingClientRect();
      return {
        bottom: rect.bottom,
        height: rect.height,
        left: rect.left,
        right: rect.right,
        top: rect.top,
        width: rect.width,
      };
    };
    return cards.map((card) => ({
      active: card.getAttribute("data-active") === "true",
      id: card.getAttribute("data-newsroom-card-id"),
      rect: rectFor(card),
      role: card.getAttribute("data-newsroom-card-template-role"),
      span: card.getAttribute("data-newsroom-card-span"),
    }));
  });
  this.newsroomCardSelection = { ...before, after, animated };
});

Then("the selected newsroom card should anchor to the top of the list view", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const pane = shell?.querySelector("[data-newsroom-list-pane='true']");
    const selectedCard = shell?.querySelector("[data-newsroom-card][data-active='true']");
    if (!(pane instanceof HTMLElement) || !(selectedCard instanceof HTMLElement)) return false;
    if (pane.scrollHeight <= pane.clientHeight + 8) return true;
    const selectedTop = selectedCard.getBoundingClientRect().top;
    const paneTop = pane.getBoundingClientRect().top;
    return Math.abs(selectedTop - paneTop) <= 14;
  }, undefined, { timeout: 8_000 });
  const report = await page.evaluate(() => {
    const shell = document.querySelector("[data-newsroom-list-detail-shell]");
    const pane = shell?.querySelector("[data-newsroom-list-pane='true']");
    const selectedCard = shell?.querySelector("[data-newsroom-card][data-active='true']");
    if (!(pane instanceof HTMLElement) || !(selectedCard instanceof HTMLElement)) return null;
    return {
      scrollTop: pane.scrollTop,
      topDelta: selectedCard.getBoundingClientRect().top - pane.getBoundingClientRect().top,
      overflowing: pane.scrollHeight > pane.clientHeight + 8,
    };
  });
  assert.ok(report, "Expected newsroom pane and selected card after card selection");
  if (!report.overflowing) return;
  assert.ok(Math.abs(report.topDelta) <= 14, `Expected selected card to anchor near the list viewport top, found delta ${report.topDelta}`);
});

Then("newsroom card selection should keep grid geometry stable", async function () {
  const selection = this.newsroomCardSelection;
  assert.ok(selection, "Expected newsroom card selection state");
  assert.ok(Array.isArray(selection.cards) && Array.isArray(selection.after), "Expected pre/post card snapshots");
  assert.equal(selection.cards.length, selection.after.length, "Expected card count to remain stable after selection");
  for (let index = 0; index < selection.cards.length; index += 1) {
    const beforeCard = selection.cards[index];
    const afterCard = selection.after[index];
    assert.equal(afterCard.id, beforeCard.id, `Expected card order stability at index ${index}`);
    assert.equal(afterCard.span, beforeCard.span, `Expected stable span for card ${beforeCard.id}`);
    assert.equal(afterCard.role, beforeCard.role, `Expected stable template role for card ${beforeCard.id}`);
    assert.ok(Math.abs(afterCard.rect.width - beforeCard.rect.width) <= 0.5, `Expected stable card width for ${beforeCard.id}`);
    assert.ok(Math.abs(afterCard.rect.height - beforeCard.rect.height) <= 0.5, `Expected stable card height for ${beforeCard.id}`);
    assert.ok(Math.abs(afterCard.rect.left - beforeCard.rect.left) <= 0.5, `Expected stable card left for ${beforeCard.id}`);
    assert.ok(Math.abs(afterCard.rect.top - beforeCard.rect.top) <= 0.5, `Expected stable card top for ${beforeCard.id}`);
  }
  assert.ok(selection.targetId, "Expected selected target id");
  const activeAfter = selection.after.find((card) => card.active);
  assert.equal(activeAfter?.id ?? null, selection.targetId, "Expected selected target card to become active");
  if (selection.activeId) {
    assert.ok(selection.after.some((card) => card.id === selection.activeId && card.active === false), "Expected previous active card to deactivate");
  }
});

Then("newsroom card selection should not animate card resizing", async function () {
  const selection = this.newsroomCardSelection;
  assert.ok(selection, "Expected newsroom card selection state");
  assert.equal(selection.animated, false, "Expected no card-level resize animation during selection changes");
});

When("I change the newsroom metric filter to {string}", async function (label) {
  const page = requirePage(this);
  const button = page.locator(".news-desk-data-grid-filter__metrics button", { hasText: label }).first();
  await button.waitFor({ state: "visible", timeout: 10_000 });
  await button.click();
  let animated = false;
  try {
    await page.waitForFunction(() => {
      const grid = document.querySelector("[data-newsroom-card-grid]");
      if (grid?.getAttribute("data-newsroom-card-grid-animating") === "true") return true;
      return Array.from(document.querySelectorAll("[data-newsroom-card]")).some((card) => {
        const transform = getComputedStyle(card).transform;
        return Boolean(transform && transform !== "none");
      });
    }, undefined, { timeout: 1_000 });
    animated = true;
  } catch {
    animated = false;
  }
  await page.waitForFunction((targetLabel) => {
    const grid = document.querySelector("[data-newsroom-card-grid]");
    if (grid?.getAttribute("data-newsroom-card-grid-animating") === "true") return false;
    const activeMetric = Array.from(document.querySelectorAll(".news-desk-data-grid-filter__metrics button[data-active='true']"))
      .map((node) => node.textContent ?? "")
      .some((text) => text.toLowerCase().includes(String(targetLabel).toLowerCase()));
    return activeMetric;
  }, label, { timeout: 5_000 });
  this.newsroomNonSelectionReflow = { animated, label };
});

Then("the newsroom card grid should animate and settle after non-selection reflow", async function () {
  const state = this.newsroomNonSelectionReflow;
  assert.ok(state, "Expected non-selection reflow state");
  assert.equal(state.animated, true, `Expected card-grid animation for non-selection reflow (${state.label})`);
});

Then("the users desk should show merge controls", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-section='administration']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-nav='users'][data-active='true']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-panel='users']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator(".news-desk-user-row", { hasText: "Demo Editor" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.locator(".news-desk-user-row", { hasText: "Demo Reader" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.locator(".news-desk-user-row button", { hasText: "Merge" }).first().waitFor({ state: "visible", timeout: 10_000 });
});

Then("the administration policies panel should render doctrine controls", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-section='administration']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-nav='policies']").click();
  await page.locator("[data-news-desk-admin-nav='policies'][data-active='true']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-panel='policies']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("textarea[data-news-desk-doctrine-input='mission']").first().waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-policy-categories]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-policy-editor]").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the administration sections panel should render section controls", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-section='administration']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-nav='sections']").click();
  await page.locator("[data-news-desk-admin-nav='sections'][data-active='true']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-panel='sections']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-admin-section='news']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-section-editor]").waitFor({ state: "visible", timeout: 10_000 });
});

When("I update newsroom section {string} title to {string} and save", async function (sectionId, title) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-admin-nav='sections']").click();
  await page.locator(`[data-news-desk-admin-section='${sectionId}']`).click();
  await page.locator("[data-news-desk-section-input='title']").first().fill(title);
  await page.locator(`[data-news-desk-section-save='${sectionId}']`).click();
});

Then("newsroom section {string} should have title {string}", async function (sectionId, title) {
  const page = requirePage(this);
  await page.locator(`[data-news-desk-admin-section='${sectionId}']`).waitFor({ state: "visible", timeout: 10_000 });
  const text = await page.locator(`[data-news-desk-admin-section='${sectionId}'] span`).first().innerText();
  assert.equal(text.trim(), title);
});

When("I move newsroom section {string} down one slot", async function (sectionId) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-admin-nav='sections']").click();
  await page.locator(`[data-news-desk-admin-section='${sectionId}']`).click();
  await page.locator("[data-news-desk-section-move='down']").click();
});

Then("newsroom section {string} should appear after {string}", async function (sectionId, previousSectionId) {
  const page = requirePage(this);
  const ids = await page.locator("[data-news-desk-admin-section]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-news-desk-admin-section")));
  const currentIndex = ids.indexOf(sectionId);
  const previousIndex = ids.indexOf(previousSectionId);
  assert.ok(currentIndex > previousIndex, `Expected ${sectionId} index ${currentIndex} to be after ${previousSectionId} index ${previousIndex}`);
});

Then("newsroom user {string} should include identity {string}", async function (userLabel, identityLabel) {
  const page = requirePage(this);
  await page.waitForFunction(
    ({ userLabel, identityLabel }) => {
      const rows = Array.from(document.querySelectorAll(".news-desk-user-row"));
      const row = rows.find((entry) => entry.textContent?.includes(userLabel));
      return Boolean(row?.textContent?.includes(identityLabel));
    },
    { userLabel, identityLabel },
  );
});

Then("newsroom user {string} should not be listed", async function (userLabel) {
  const page = requirePage(this);
  await page.waitForFunction((label) => (
    !Array.from(document.querySelectorAll(".news-desk-user-row")).some((entry) => entry.textContent?.includes(label))
  ), userLabel);
});

Then("the assignments desk should render", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-tab='assignments'][aria-current='page']").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-assignments]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-newsroom-card-grid]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator('[data-newsroom-card][data-assignment-candidate="assignment-demo-reference-intake-history-001"]').waitFor({ state: "visible", timeout: 10_000 });
  await page.locator('[data-newsroom-card][data-assignment-candidate="assignment-demo-reference-intake-history-002"][data-assignment-status="claimed"]').waitFor({ state: "visible", timeout: 10_000 });
  const detailOpen = await page.locator("[data-news-desk-assignments]").first().getAttribute("data-detail-open");
  assert.equal(detailOpen, "false", `Expected assignments detail to start closed, found ${detailOpen}`);
});

Then("the newsroom should show an editor access gate", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-access]").waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("text=Editor Sign-In Required").first().waitFor({ state: "visible", timeout: 10_000 });
});

Then("the newsroom should not show an editor access gate", async function () {
  const page = requirePage(this);
  assert.equal(await page.locator("[data-news-desk-access]").count(), 0);
});

Then("the newsroom aggregate counts should remain blank while the summary is loading", async function () {
  const page = requirePage(this);
  const report = await page.evaluate(() => {
    const labels = ["Messages", "Assignments", "References", "Topics", "Concepts"];
    return labels.map((label) => {
      const tab = Array.from(document.querySelectorAll("[data-news-desk-tab]"))
        .find((node) => node.textContent?.includes(label));
      const count = tab?.querySelector(".news-desk-tab__count");
      return {
        label,
        exists: Boolean(tab),
        visible: count?.getAttribute("data-count-visible"),
        text: count?.textContent?.trim() ?? "",
      };
    });
  });
  for (const entry of report) {
    assert.ok(entry.exists, `Expected newsroom tab for ${entry.label}`);
    assert.equal(entry.visible, "false", `Expected ${entry.label} count to stay hidden while the summary loads`);
    assert.equal(entry.text, "", `Expected ${entry.label} count text to stay blank while the summary loads`);
  }
});

Then("the newsroom aggregate counts should show question marks", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => {
    const labels = ["Messages", "Assignments", "References", "Topics", "Concepts"];
    return labels.every((label) => {
      const tab = Array.from(document.querySelectorAll("[data-news-desk-tab]"))
        .find((node) => node.textContent?.includes(label));
      const count = tab?.querySelector(".news-desk-tab__count");
      return count?.getAttribute("data-count-visible") === "true" && (count.textContent?.trim() ?? "") === "?";
    });
  }, { timeout: 10_000 });
  const report = await page.evaluate(() => {
    const labels = ["Messages", "Assignments", "References", "Topics", "Concepts"];
    return labels.map((label) => {
      const tab = Array.from(document.querySelectorAll("[data-news-desk-tab]"))
        .find((node) => node.textContent?.includes(label));
      const count = tab?.querySelector(".news-desk-tab__count");
      return {
        label,
        exists: Boolean(tab),
        visible: count?.getAttribute("data-count-visible"),
        text: count?.textContent?.trim() ?? "",
      };
    });
  });
  for (const entry of report) {
    assert.ok(entry.exists, `Expected newsroom tab for ${entry.label}`);
    assert.equal(entry.visible, "true", `Expected ${entry.label} count slot to be visible when the summary is missing`);
    assert.equal(entry.text, "?", `Expected ${entry.label} count to render a question mark when the summary is missing`);
  }
});

Then("the newsroom should not show a summary error banner", async function () {
  const page = requirePage(this);
  const banners = await page.locator(".category-steering-alert").allTextContents();
  const summaryBanner = banners.find((text) => /summary unavailable|specified key does not exist/i.test(text));
  assert.equal(summaryBanner, undefined, `Expected no summary error banner, found: ${summaryBanner}`);
});

Then("the message detail headline should be {string}", async function (expectedHeadline) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-message-headline]").waitFor({ state: "visible", timeout: 10_000 });
  await page.waitForFunction((expected) => {
    const headline = document.querySelector("[data-news-desk-message-headline]");
    return (headline?.textContent?.trim() ?? "") === expected;
  }, expectedHeadline, { timeout: 10_000 });
  const headline = (await page.locator("[data-news-desk-message-headline]").textContent())?.trim() ?? "";
  assert.equal(headline, expectedHeadline);
});

Then("the message detail subheading should be {string}", async function (expectedSubheading) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-message-subheading]").waitFor({ state: "visible", timeout: 10_000 });
  await page.waitForFunction((expected) => {
    const subheading = document.querySelector("[data-news-desk-message-subheading]");
    return (subheading?.textContent?.trim() ?? "") === expected;
  }, expectedSubheading, { timeout: 10_000 });
  const subheading = (await page.locator("[data-news-desk-message-subheading]").textContent())?.trim() ?? "";
  assert.equal(subheading, expectedSubheading);
});

Then("the message detail summary should be {string}", async function (expectedSummary) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-message-summary]").waitFor({ state: "visible", timeout: 10_000 });
  await page.waitForFunction((expected) => {
    const summary = document.querySelector("[data-news-desk-message-summary] strong");
    return (summary?.textContent?.trim() ?? "") === expected;
  }, expectedSummary, { timeout: 10_000 });
  const summary = (await page.locator("[data-news-desk-message-summary] strong").textContent())?.trim() ?? "";
  assert.equal(summary, expectedSummary);
});

Then("the message detail headline should not be {string}", async function (unexpectedHeadline) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-message-headline]").waitFor({ state: "visible", timeout: 10_000 });
  const headline = (await page.locator("[data-news-desk-message-headline]").textContent())?.trim() ?? "";
  assert.notEqual(headline, unexpectedHeadline);
});

Then("the newsroom should show category proposal queue rows", async function () {
  const page = requirePage(this);
  await page.locator("[data-topic-queue-proposal]").first().waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-topic-queue-proposal] td", { hasText: "create-category" }).first().waitFor({ state: "visible", timeout: 10_000 });
});

Then("the newsroom should show accepted subcategories under canonical categories", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-category-tree-root='category.foundation-model-scaling']").first().waitFor({ state: "attached", timeout: 10_000 });
  await page.locator("[data-news-desk-subcategory='category.agent-memory']", { hasText: "Agent Memory" }).first().waitFor({ state: "attached", timeout: 10_000 });
  await page.locator("[data-news-desk-subcategory='category.benchmark-saturation']", { hasText: "Benchmark Saturation" }).first().waitFor({ state: "attached", timeout: 10_000 });
});

Then("the newsroom should show proposed subcategories under canonical categories", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-category-tree-root='category.foundation-model-scaling']").first().waitFor({ state: "attached", timeout: 10_000 });
  await page.locator("[data-news-desk-proposed-subcategory='category.agent-memory']", { hasText: "Agent Memory" }).first().waitFor({ state: "attached", timeout: 10_000 });
});

Then("the newsroom should offer accept reject defer and edit actions", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-proposed-subcategory='category.agent-memory'] [data-review-action='accept']").first().waitFor({ state: "attached", timeout: 10_000 });
  await page.locator("[data-news-desk-proposed-subcategory='category.agent-memory'] [data-review-action='reject']").first().waitFor({ state: "attached", timeout: 10_000 });
  await page.locator("[data-news-desk-proposed-subcategory='category.agent-memory'] [data-review-action='defer']").first().waitFor({ state: "attached", timeout: 10_000 });
  await page.locator("[data-news-desk-proposed-subcategory='category.agent-memory'] [data-review-action='edit']").first().waitFor({ state: "attached", timeout: 10_000 });
});

Then("the first newsroom category name should be {string}", async function (expectedName) {
  const value = await requirePage(this)
    .locator(".category-steering-category-card label", { hasText: "Name" })
    .first()
    .locator("input")
    .inputValue();
  assert.equal(value, expectedName);
});

Then("assignment {string} should be claimed", async function (assignmentId) {
  const page = requirePage(this);
  await page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"][data-assignment-status="claimed"]`).waitFor({ state: "visible", timeout: 10_000 });
});

Then("assignment {string} should be completed", async function (assignmentId) {
  await requirePage(this)
    .locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"][data-assignment-status="completed"]`)
    .waitFor({ state: "visible", timeout: 10_000 });
});

Then("assignment {string} should show a private reporting packet", async function (assignmentId) {
  const page = requirePage(this);
  const candidate = page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator("text=reporting.edition-candidate").waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator("text=Reporting packet").waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator("text=Reporting context packet: model-release accountability angle").waitFor({ state: "visible", timeout: 10_000 });
});

When("I switch assignments to Story Budget view", async function () {
  const page = requirePage(this);
  await page.getByRole("button", { name: "Story Budget" }).click();
  await page.locator("[data-reporting-story-budget]").waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reporting story budget should show section {string} with {int} slot and {int} candidate", async function (sectionKey, slotCount, candidateCount) {
  const page = requirePage(this);
  const section = page.locator(`[data-story-budget-section="${sectionKey}"]`);
  await section.waitFor({ state: "visible", timeout: 10_000 });
  await section.locator(`[data-story-budget-metric="slots"]`, { hasText: `${slotCount} slots` }).waitFor({ state: "visible", timeout: 10_000 });
  await section.locator(`[data-story-budget-metric="dispatched"]`, { hasText: `${candidateCount} dispatched` }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reporting story budget should map candidate {string} to slot rank {int}", async function (assignmentId, slotRank) {
  const page = requirePage(this);
  const slot = page.locator(`[data-story-budget-slot]`, { has: page.locator(`[data-story-budget-candidate="${assignmentId}"]`) });
  await slot.waitFor({ state: "visible", timeout: 10_000 });
  await slot.locator(`text=Slot ${slotRank}`).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the reporting story budget should show section {string} with {int} filled slot and {int} unresolved slot", async function (sectionKey, filledSlotCount, unresolvedSlotCount) {
  const page = requirePage(this);
  const section = page.locator(`[data-story-budget-section="${sectionKey}"]`);
  await section.waitFor({ state: "visible", timeout: 10_000 });
  await section.locator(`[data-story-budget-metric="filled-slots"]`, { hasText: `${filledSlotCount} filled slots` }).waitFor({ state: "visible", timeout: 10_000 });
  await section.locator(`[data-story-budget-metric="unresolved-slots"]`, { hasText: `${unresolvedSlotCount} unresolved slots` }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("story budget candidate {string} should show packet recommendation {string}", async function (assignmentId, recommendation) {
  const page = requirePage(this);
  const candidate = page.locator(`[data-story-budget-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator(`[data-story-budget-recommendation="${recommendation}"]`).waitFor({ state: "visible", timeout: 10_000 });
});

Then("story budget candidate {string} should show risk and gap context", async function (assignmentId) {
  const page = requirePage(this);
  const candidate = page.locator(`[data-story-budget-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator("text=Risks").waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator("text=Gaps").waitFor({ state: "visible", timeout: 10_000 });
});

When("I review story budget candidate {string} as {string}", async function (assignmentId, decision) {
  const page = requirePage(this);
  const candidate = page.locator(`[data-story-budget-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator(`[data-story-budget-decision="${decision}"]`).click();
});

Then("story budget candidate {string} should show reporting decision {string}", async function (assignmentId, decision) {
  const page = requirePage(this);
  await page.waitForFunction(
    ({ id, expected }) => document.querySelector(`[data-story-budget-candidate="${id}"]`)?.getAttribute("data-reporting-decision") === expected,
    { id: assignmentId, expected: decision },
  );
});

When("I review reporting packet for assignment {string} as {string} with note {string}", async function (assignmentId, decision, note) {
  const page = requirePage(this);
  const candidate = page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await candidate.locator(`[data-assignment-reason="${assignmentId}"]`).fill(note);
  const labelByDecision = {
    brief: "Make Brief",
    hold: "Hold Packet",
    kill: "Kill Packet",
    merge: "Merge Packet",
    select: "Select Packet",
  };
  const label = labelByDecision[decision];
  assert.ok(label, `Unsupported reporting decision ${decision}`);
  await page.getByRole("button", { name: label }).click();
});

Then("assignment {string} should show reporting decision {string}", async function (assignmentId, decision) {
  const page = requirePage(this);
  const candidate = page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`);
  await candidate.waitFor({ state: "visible", timeout: 10_000 });
  await page.waitForFunction(
    ({ id, expected }) => document.querySelector(`.news-desk-assignment-row[data-assignment-candidate="${id}"]`)?.getAttribute("data-reporting-decision") === expected,
    { id: assignmentId, expected: decision },
  );
});

Then("assignment {string} should show a copywriting assignment without edition placement", async function (assignmentId) {
  const page = requirePage(this);
  const candidate = page.locator(`.news-desk-assignment-row[data-assignment-candidate="${assignmentId}"]`);
  await candidate.locator("[data-reporting-copywriting-assignment]").waitFor({ state: "visible", timeout: 10_000 });
  const editionItemCount = await page.locator("[data-edition-item-id], [data-edition-item]").count();
  assert.equal(editionItemCount, 0, "Expected no EditionItem placement nodes in assignment review");
});

Then("story budget candidate {string} should show a copywriting assignment", async function (assignmentId) {
  const page = requirePage(this);
  const candidate = page.locator(`[data-story-budget-candidate="${assignmentId}"]`);
  await candidate.locator("[data-reporting-copywriting-assignment]").waitFor({ state: "visible", timeout: 10_000 });
});

Then("assignment {string} should not appear as an edition item", async function (assignmentId) {
  const report = await requirePage(this).evaluate((id) => {
    const editionAnchors = Array.from(document.querySelectorAll("a[href]"))
      .map((anchor) => anchor.getAttribute("href") ?? "")
      .filter((href) => href.includes(id) && !href.includes("/newsroom/assignments"));
    const editionItemNodes = Array.from(document.querySelectorAll("[data-edition-item-id], [data-edition-item]"))
      .map((node) => ({
        id: node.getAttribute("data-edition-item-id") ?? node.getAttribute("data-edition-item") ?? "",
        text: node.textContent ?? "",
      }))
      .filter((node) => node.id.includes(id) || node.text.includes(id));
    return { editionAnchors, editionItemNodes };
  }, assignmentId);
  assert.deepEqual(report.editionAnchors, [], `Expected no reader edition link for ${assignmentId}`);
  assert.deepEqual(report.editionItemNodes, [], `Expected no EditionItem node for ${assignmentId}`);
});

Then("edition page count should not include appended Newsroom pages", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => document.querySelector(".site-shell")?.getAttribute("data-news-desk-appendix-ready") === "true");
  const report = await page.evaluate(() => ({
    solvedPages: window.__PAPYRUS_LAYOUT__?.pages.length ?? 0,
    totalPages: window.__PAPYRUS_TOTAL_PAGES__ ?? 0,
  }));
  assert.ok(report.solvedPages > 0, "Expected solved edition pages");
  assert.equal(report.totalPages, report.solvedPages);
});

Then("edition page count should include appended Newsroom pages", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => document.querySelector(".site-shell")?.getAttribute("data-news-desk-appendix-ready") === "true");
  await page.waitForFunction(() => {
    const solvedPages = window.__PAPYRUS_LAYOUT__?.pages.length ?? 0;
    const totalPages = window.__PAPYRUS_TOTAL_PAGES__ ?? 0;
    return solvedPages > 0 && totalPages > solvedPages;
  });
  const report = await page.evaluate(() => ({
    solvedPages: window.__PAPYRUS_LAYOUT__?.pages.length ?? 0,
    totalPages: window.__PAPYRUS_TOTAL_PAGES__ ?? 0,
  }));
  assert.ok(report.solvedPages > 0, "Expected solved edition pages");
  assert.ok(
    report.totalPages > report.solvedPages,
    `Expected appended Newsroom pages; solved=${report.solvedPages}, total=${report.totalPages}`,
  );
});

Then("no Newsroom appendix pages should render", async function () {
  const page = requirePage(this);
  const appendixCount = await page.locator("[data-news-desk-appendix-page]").count();
  assert.equal(appendixCount, 0);
});

Then("the front page footer should not link to the newsroom", async function () {
  const page = requirePage(this);
  if (!this.capabilities?.supportsNewspaper) {
    return;
  }
  await page.waitForFunction(() => window.__PAPYRUS_LAYOUT__ && document.querySelector(".front-footer"));
  const newsDeskLinks = await page.locator('.front-footer [data-footer-utility="newsDesk"]').count();
  assert.equal(newsDeskLinks, 0);
});

Then("the final edition pages should include the canonical category register", async function () {
  const page = requirePage(this);
  await page.locator("[data-news-desk-appendix-page='register'] h2", { hasText: "Canonical Category Register" }).waitFor({ state: "visible", timeout: 10_000 });
  await page.locator("[data-news-desk-category-register]", { hasText: "Foundation Model Scaling" }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the root category appendix page should show subcategory {string}", async function (subcategoryName) {
  const page = requirePage(this);
  await page.locator("[data-news-desk-appendix-page='category'] .news-desk-appendix__subcategory", { hasText: subcategoryName }).waitFor({ state: "visible", timeout: 10_000 });
});

Then("the appendix page should use newspaper page styling", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active .paper-page-content--news-desk-appendix");
    if (!active) return null;
    const style = getComputedStyle(active);
    return {
      backgroundImage: style.backgroundImage,
      boxShadow: style.boxShadow,
      fontFamily: style.fontFamily,
    };
  });
  assert.ok(report, "Expected active Newsroom appendix page");
  assert.notEqual(report.backgroundImage, "none", "Expected paper background on appendix page");
  assert.notEqual(report.boxShadow, "none", "Expected paper shadow on appendix page");
  assert.match(report.fontFamily, /Georgia|Times/i);
});

Then("the Newsroom appendix should not overflow horizontally", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active .paper-page-content--news-desk-appendix");
    return {
      documentScrollWidth: document.documentElement.scrollWidth,
      documentClientWidth: document.documentElement.clientWidth,
      activeScrollWidth: active?.scrollWidth ?? 0,
      activeClientWidth: active?.clientWidth ?? 0,
    };
  });
  assert.ok(
    report.documentScrollWidth <= report.documentClientWidth + 2,
    `Expected document not to overflow horizontally; scrollWidth=${report.documentScrollWidth}, clientWidth=${report.documentClientWidth}`,
  );
  assert.ok(
    report.activeScrollWidth <= report.activeClientWidth + 2,
    `Expected appendix not to overflow horizontally; scrollWidth=${report.activeScrollWidth}, clientWidth=${report.activeClientWidth}`,
  );
});

Then("the active edition should expose a composable layout plan", async function () {
  const templateId = await requirePage(this).locator(".site-shell").getAttribute("data-layout-plan-front-template");
  assert.equal(templateId, "front.mosaic");
});

Then("the active edition should include article {string}", async function (expectedSlug) {
  const articleSlugs = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const slugs = layout?.pages.flatMap((page) => (
      page.regions.flatMap((region) => (
        region.blocks.map((block) => block.article?.slug).filter(Boolean)
      ))
    )) ?? [];
    return Array.from(new Set(slugs));
  });

  assert.ok(
    articleSlugs.includes(expectedSlug),
    `Expected active edition to include ${expectedSlug}; found ${articleSlugs.join(", ")}`,
  );
});

Then("the front page masthead edition label should say {string}", async function (expectedLabel) {
  const label = await requirePage(this).evaluate(() => {
    const activeFrontPage = document.querySelector(".paper-page--active .paper-page-content--front");
    if (!activeFrontPage) return null;
    const value = activeFrontPage.querySelector(".masthead__meta > :last-child")?.textContent ?? "";
    return value.trim();
  });
  assert.equal(label, expectedLabel);
});

Then("edition pages should sit on a neutral gray substrate with one rhythm row between pages", async function () {
  const report = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const shell = document.querySelector(".site-shell");
    const scrollEdition = document.querySelector(".scroll-edition");
    const pageContent = document.querySelector(".paper-page-content");
    if (!layout || !shell || !scrollEdition || !pageContent) return null;
    return {
      rhythm: layout.rhythm.rowHeight,
      shellBackground: getComputedStyle(shell).backgroundColor,
      editionBackground: getComputedStyle(scrollEdition).backgroundColor,
      pageGap: Number.parseFloat(getComputedStyle(scrollEdition).rowGap),
      pageShadow: getComputedStyle(pageContent).boxShadow,
    };
  });
  assert.ok(report, "Expected edition substrate report");
  assert.equal(report.shellBackground, "rgb(128, 128, 128)");
  assert.equal(report.editionBackground, "rgb(128, 128, 128)");
  assert.ok(Math.abs(report.pageGap - report.rhythm) <= 0.75, `Expected page gap ${report.pageGap} to equal rhythm ${report.rhythm}`);
  assert.notEqual(report.pageShadow, "none", "Expected paper pages to cast a downward shadow");
});

Then("the front page should label article {string} as continued on page {int}", async function (articleId, pageNumber) {
  const continuationPageNumber = await requirePage(this).evaluate((targetArticleId) => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const frontPage = layout?.pages.find((page) => page.pageNumber === 1);
    return frontPage?.regions
      .flatMap((region) => region.blocks)
      .find((block) => block.article?.slug === targetArticleId)?.jumpTargetPage ?? null;
  }, articleId);

  assert.equal(continuationPageNumber, pageNumber);
});

Then("the article page should show headline {string}", async function (expectedHeadline) {
  const headlineLocator = requirePage(this).locator(".article-page h1");
  await headlineLocator.waitFor({ state: "visible", timeout: 10_000 });
  const headline = await headlineLocator.innerText();
  assert.equal(headline, expectedHeadline);
});

Then("the article page should show deck {string}", async function (expectedDeck) {
  await requirePage(this).locator(".article-deck").waitFor({ state: "visible", timeout: 10_000 });
  const deck = await requirePage(this).locator(".article-deck").innerText();
  assert.equal(deck, expectedDeck);
});

Then("the article back link should target {string}", async function (expectedTarget) {
  const href = await requirePage(this).locator(".article-nav a").first().getAttribute("href");
  assert.equal(href, expectedTarget);
});

Then("the browser path should be {string}", async function (expectedPath) {
  const actualPath = await requirePage(this).evaluate(() => window.location.pathname);
  assert.equal(actualPath, expectedPath);
});

Then("the browser hash should be {string}", async function (expectedHash) {
  await requirePage(this).waitForFunction((hash) => window.location.hash === hash, expectedHash, { timeout: 10_000 });
  const actualHash = await requirePage(this).evaluate(() => window.location.hash);
  assert.equal(actualHash, expectedHash);
});

When("I switch presentation to {string}", async function (label) {
  const page = requirePage(this);
  const button = page.locator(".presentation-switcher__button", { hasText: label }).first();
  await button.waitFor({ state: "visible", timeout: 10_000 });
  await button.click();
});

When("I choose reader format {string}", async function (label) {
  const page = requirePage(this);
  if (!this.capabilities?.allowsPresentationChoice) {
    const lockedLabel = getPresentationFormatLabel(this.getEffectivePresentation());
    assert.equal(lockedLabel, label, `Expected locked reader format ${lockedLabel}; site does not allow format changes`);
    return;
  }
  const button = page.locator(".format-card", { hasText: label }).first();
  await button.waitFor({ state: "visible", timeout: 10_000 });
  await button.click();
});

Given("the site allows presentation choice", async function () {
  this.requireCapability("presentation-choice");
});

Given("the active presentation is {string}", async function (expectedPresentation) {
  const normalized = expectedPresentation.toLowerCase();
  const capabilities = this.capabilities;
  const settings = {
    theme: capabilities?.siteBrand === "threat-intelligence" ? "light" : "system",
    presentation: normalized,
    motion: "standard",
  };
  if (capabilities?.forcedPresentation) {
    assert.equal(
      capabilities.forcedPresentation,
      normalized,
      `Expected forced presentation ${capabilities.forcedPresentation}; found request for ${normalized}`,
    );
    this.pendingReaderSettings = settings;
    return;
  }

  this.pendingReaderSettings = settings;
  const page = this.page;
  if (page) {
    await page.evaluate((nextSettings) => {
      window.localStorage.setItem("papyrus:reader-settings", JSON.stringify(nextSettings));
      window.dispatchEvent(new CustomEvent("papyrus:settings-changed"));
    }, settings);
  }
});

Then("the active presentation should be {string}", async function (expectedPresentation) {
  const page = requirePage(this);
  const normalized = expectedPresentation.toLowerCase();
  await page.waitForFunction((presentation) => {
    if (presentation === "newspaper") return Boolean(document.querySelector(".site-shell"));
    return document.querySelector("[data-presentation-engine]")?.getAttribute("data-presentation-engine") === presentation;
  }, normalized, { timeout: 10_000 });
});

Then("the reader presentation switcher should not render", async function () {
  const count = await requirePage(this).locator(".presentation-switcher").count();
  assert.equal(count, 0);
});

Then("reader format {string} should be selected", async function (label) {
  const page = requirePage(this);
  if (!this.capabilities?.allowsPresentationChoice) {
    const lockedLabel = getPresentationFormatLabel(this.getEffectivePresentation());
    assert.equal(lockedLabel, label, `Expected locked reader format ${lockedLabel}`);
    return;
  }
  await page.waitForFunction((expectedLabel) => {
    const selected = Array.from(document.querySelectorAll(".format-card")).find((card) => (
      card.getAttribute("data-selected") === "true"
    ));
    return selected?.textContent?.includes(expectedLabel);
  }, label, { timeout: 10_000 });
});

Then("settings should be saved in this browser", async function () {
  const page = requirePage(this);
  await page.waitForFunction(() => (
    document.querySelector(".settings-status")?.textContent?.includes("Saved in this browser")
  ), { timeout: 10_000 });
});

Then("presentation section {string} should render", async function (sectionKey) {
  await requirePage(this)
    .locator(`[data-edition-section='${sectionKey}']`)
    .waitFor({ state: "visible", timeout: 10_000 });
});

Then("presentation item {string} should render with measured lines", async function (itemSlug) {
  const item = requirePage(this).locator(`.presentation-item[data-item-id='${itemSlug}']`).first();
  await item.waitFor({ state: "visible", timeout: 10_000 });
  const lineCount = await item.locator(".presentation-measured-line").count();
  assert.ok(lineCount > 0, `Expected ${itemSlug} to render measured Pretext lines`);
});

Then("the blog presentation footer should list edition sections", async function () {
  const report = await requirePage(this).evaluate(() => {
    const footer = document.querySelector('[data-presentation-engine="blog"] [data-presentation-footer="true"]');
    if (!footer) return null;
    return Array.from(footer.querySelectorAll(".front-footer__section-link")).map((link) => ({
      section: link.getAttribute("data-footer-section"),
      text: link.textContent?.replace(/\s+/g, " ").trim() ?? "",
      href: link instanceof HTMLAnchorElement ? link.href : null,
    }));
  });
  assert.ok(report, "Expected blog presentation footer");
  assert.ok(report.length > 0, "Expected at least one blog footer section link");
  for (const entry of report) {
    assert.ok(entry.section, "Expected footer section label");
    assert.ok(entry.text.length > entry.section.length, `Expected footer text for section ${entry.section}`);
    assert.ok(entry.href?.includes("#"), `Expected footer href to include an item anchor; found ${entry.href}`);
  }
});

Then("the blog presentation footer should include utility links", async function () {
  const report = await requirePage(this).evaluate(() => {
    const footer = document.querySelector('[data-presentation-engine="blog"] [data-presentation-footer="true"]');
    if (!footer) return null;
    return Array.from(footer.querySelectorAll("[data-footer-utility]")).map((entry) => entry.getAttribute("data-footer-utility"));
  });
  assert.ok(report, "Expected blog presentation footer utilities");
  assert.deepEqual(report, ["archive", "newsDesk", "settings", "login"]);
});

Then("edition section route {string} should target section {string}", function (routePath, expectedSectionKey) {
  const route = parseDatedTestPath(routePath);
  const { parseEditionSectionRoute } = loadEditionRoutesModule();
  const parsed = parseEditionSectionRoute({ ...route, sectionKey: route.sectionKey });
  assert.equal(parsed?.sectionKey, expectedSectionKey);
  assert.equal(parsed?.canonicalPath, routePath);
});

Then("edition item route {string} should target item {string}", function (routePath, expectedItemSlug) {
  const route = parseDatedTestPath(routePath);
  const { parseEditionArticleRoute } = loadEditionRoutesModule();
  const parsed = parseEditionArticleRoute({ ...route, articleSlug: route.articleSlug });
  assert.equal(parsed?.articleSlug, expectedItemSlug);
  assert.equal(parsed?.canonicalPath, routePath);
});

Then("article {string} should have exactly one edition anchor", async function (articleId) {
  await requirePage(this).waitForFunction(
    (targetArticleId) => Array.from(document.querySelectorAll("[id]")).some((element) => element.id === targetArticleId),
    articleId,
    { timeout: 10_000 },
  );
  const anchorCount = await requirePage(this).evaluate((targetArticleId) => (
    Array.from(document.querySelectorAll("[id]")).filter((element) => element.id === targetArticleId).length
  ), articleId);
  assert.equal(anchorCount, 1);
});

Then("no measured line should be cropped", async function () {
  const report = await getActivePageReport(requirePage(this));
  assert.deepEqual(report.clippedLines, []);
});

Then("no solved furniture should overlap within a section", async function () {
  const report = await getActivePageReport(requirePage(this));
  assert.deepEqual(report.furnitureOverlaps, []);
});

Then("no measured line should overlap solved furniture", async function () {
  const report = await getActivePageReport(requirePage(this));
  assert.deepEqual(report.lineFurnitureOverlaps, []);
});

Then("no article chrome should overlap", async function () {
  const report = await getActivePageReport(requirePage(this));
  assert.deepEqual(report.chromeOverlaps, []);
});

Then("the active page should follow the vertical rhythm", async function () {
  const report = await getActiveRhythmReport(requirePage(this));
  assert.deepEqual(report.errors, []);
});

Then("the masthead should use {int} rhythm rows with {int} title rows and fit the page width", async function (expectedMastheadRows, expectedTitleRows) {
  const report = await requirePage(this).evaluate(() => {
    const masthead = document.querySelector(".masthead");
    const title = masthead?.querySelector("h1");
    const titleInner = title?.querySelector("span, a");
    if (!masthead || !title || !titleInner) return null;
    const mastheadRect = masthead.getBoundingClientRect();
    const titleRect = titleInner.getBoundingClientRect();
    const mastheadStyle = getComputedStyle(masthead);
    const titleStyle = getComputedStyle(title);
    const rhythm = Number.parseFloat(mastheadStyle.getPropertyValue("--paper-rhythm")) || 19;
    const metaItems = Array.from(masthead.querySelectorAll(".masthead__meta > *")).map((item) => {
      const rect = item.getBoundingClientRect();
      const style = getComputedStyle(item);
      return {
        display: style.display,
        height: rect.height,
        text: item.textContent?.trim() ?? "",
        visibility: style.visibility,
        width: rect.width,
      };
    });
    return {
      rhythm,
      mastheadHeight: mastheadRect.height,
      mastheadWidth: mastheadRect.width,
      metaItems,
      titleLineHeight: Number.parseFloat(titleStyle.lineHeight),
      titleWidth: titleRect.width,
    };
  });
  assert.ok(report, "Expected masthead report");
  const tolerance = 0.75;
  assert.ok(
    Math.abs(report.mastheadHeight - report.rhythm * expectedMastheadRows) <= tolerance,
    `Expected masthead height ${report.mastheadHeight} to be ${expectedMastheadRows} rhythm rows`,
  );
  assert.ok(
    Math.abs(report.titleLineHeight - report.rhythm * expectedTitleRows) <= tolerance,
    `Expected title line-height ${report.titleLineHeight} to be ${expectedTitleRows} rhythm rows`,
  );
  assert.ok(
    report.titleWidth <= report.mastheadWidth + tolerance,
    `Expected masthead title width ${report.titleWidth} to fit within ${report.mastheadWidth}`,
  );
  assert.equal(
    report.metaItems.filter((item) => item.display !== "none" && item.visibility !== "hidden" && item.width > 0 && item.height > 0).length,
    3,
  );
});

Then("the newsroom masthead should fit width and align to rhythm rows", async function () {
  const report = await requirePage(this).evaluate(() => {
    const masthead = document.querySelector(".news-desk-masthead");
    const title = masthead?.querySelector("h1");
    const titleInner = masthead?.querySelector("h1 span, h1 a");
    if (!masthead || !title || !titleInner) return null;
    const mastheadRect = masthead.getBoundingClientRect();
    const titleRectOuter = title.getBoundingClientRect();
    const titleRect = titleInner.getBoundingClientRect();
    const style = getComputedStyle(masthead);
    const rhythm = Number.parseFloat(style.getPropertyValue("--paper-rhythm")) || 19;
    const heightRows = mastheadRect.height / rhythm;
    const titleRows = titleRectOuter.height / rhythm;
    return { heightRows, mastheadWidth: mastheadRect.width, rhythm, titleRows, titleWidth: titleRect.width };
  });
  assert.ok(report, "Expected newsroom masthead rhythm report");
  const tolerance = 0.08;
  assert.ok(Math.abs(report.heightRows - Math.round(report.heightRows)) <= tolerance, `Expected masthead height rows integer, got ${report.heightRows}`);
  assert.ok(Math.abs(report.titleRows - Math.round(report.titleRows)) <= tolerance, `Expected masthead title rows integer, got ${report.titleRows}`);
  assert.ok(report.titleWidth <= report.mastheadWidth + 0.75, `Expected masthead title width ${report.titleWidth} to fit within ${report.mastheadWidth}`);
});

Then("the newsroom tabs should use {int} columns", async function (expectedColumns) {
  const report = await requirePage(this).evaluate(() => {
    const tabs = Array.from(document.querySelectorAll("[data-news-desk-tab]"));
    if (!tabs.length) return null;
    const rects = tabs.map((tab) => tab.getBoundingClientRect()).filter((rect) => rect.width > 0 && rect.height > 0);
    if (!rects.length) return null;
    const firstTop = rects[0].top;
    const firstRow = rects.filter((rect) => Math.abs(rect.top - firstTop) <= 0.75);
    return { firstRowCount: firstRow.length };
  });
  assert.ok(report, "Expected newsroom tabs column report");
  assert.equal(report.firstRowCount, expectedColumns, `Expected newsroom tabs first row to have ${expectedColumns} columns`);
});

Then("no continuation column should be dead", async function () {
  const report = await getActivePageReport(requirePage(this));
  assert.deepEqual(report.deadColumns, []);
});

Then("the solved layout should use {int} columns", async function (expectedColumnCount) {
  const columnCount = await requirePage(this).evaluate(() => window.__PAPYRUS_LAYOUT__?.columnCount ?? null);
  assert.equal(columnCount, expectedColumnCount);
});

Then("the {string} section should show a responsive image inset", async function (articleId) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.ok(solverSection.image, `Expected ${articleId} to have a solved image`);
  assert.ok(solverSection.image.columnSpan >= 1, `Expected ${articleId} image to occupy at least one column`);
  assert.ok(
    String(solverSection.image.templateId).startsWith("image-"),
    `Expected responsive image template id; found ${solverSection.image.templateId}`,
  );
});

Then("the {string} section image should span {int} columns", async function (articleId, expectedSpan) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.equal(solverSection.image?.columnSpan, expectedSpan);
});

Then("the {string} section image should leave one rhythm row before copy", async function (articleId) {
  const report = await requirePage(this).evaluate((targetArticleId) => {
    const active = document.querySelector(".paper-page--active");
    const layout = window.__PAPYRUS_LAYOUT__;
    const section = Array.from(active?.querySelectorAll(".solved-block--articleFrame, .front-story") ?? [])
      .find((candidate) => candidate.getAttribute("data-article-id") === targetArticleId);
    const image = section?.querySelector(".continuation-photo, .lead-photo, .front-prelude-photo");
    if (!layout || !section || !image) return null;
    const imageRect = image.getBoundingClientRect();
    const followingLines = Array.from(section.querySelectorAll(".measured-line"))
      .map((line) => line.getBoundingClientRect())
      .filter((lineRect) => (
        lineRect.left < imageRect.right - 0.75 &&
        lineRect.right > imageRect.left + 0.75 &&
        lineRect.top >= imageRect.bottom - 0.75
      ))
      .sort((first, second) => first.top - second.top);
    const forbiddenLines = followingLines.filter((lineRect) => lineRect.top < imageRect.bottom + layout.rhythm.rowHeight - 0.75);
    return {
      gap: followingLines[0] ? followingLines[0].top - imageRect.bottom : null,
      forbiddenLines: forbiddenLines.map((lineRect) => ({ top: lineRect.top, bottom: lineRect.bottom })),
      imageBottom: imageRect.bottom,
      firstCopyTop: followingLines[0]?.top ?? null,
      rhythm: layout.rhythm.rowHeight,
    };
  }, articleId);

  assert.ok(report, `Expected rendered image/copy geometry for ${articleId}`);
  assert.deepEqual(report.forbiddenLines, [], `Expected the row after ${articleId} image caption to stay blank`);
  if (report.gap !== null) {
    assert.ok(
      report.gap >= report.rhythm - 0.75,
      `Expected one rhythm row between image and copy for ${articleId}; found ${report.gap}px with rhythm ${report.rhythm}px`,
    );
  }
});

Then("the {string} section adjacent copy should flow beside the image", async function (articleId) {
  const report = await requirePage(this).evaluate((targetArticleId) => {
    const active = document.querySelector(".paper-page--active");
    const layout = window.__PAPYRUS_LAYOUT__;
    const section = Array.from(active?.querySelectorAll(".solved-block--articleFrame, .front-story") ?? [])
      .find((candidate) => candidate.getAttribute("data-article-id") === targetArticleId);
    const image = section?.querySelector(".continuation-photo, .lead-photo, .front-prelude-photo");
    if (!layout || !section || !image) return null;
    const imageRect = image.getBoundingClientRect();
    const adjacentLines = Array.from(section.querySelectorAll(".measured-line"))
      .map((line) => {
        const rect = line.getBoundingClientRect();
        return { text: line.textContent, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
      })
      .filter((lineRect) => {
        const horizontallyOverlapsImage = lineRect.left < imageRect.right - 0.75 && lineRect.right > imageRect.left + 0.75;
        const verticallyBesideImage = lineRect.top >= imageRect.top - 0.75 && lineRect.top < imageRect.bottom - 0.75;
        return !horizontallyOverlapsImage && verticallyBesideImage;
      });
    return {
      adjacentLineCount: adjacentLines.length,
      sample: adjacentLines.slice(0, 3),
      imageRect: {
        left: imageRect.left,
        right: imageRect.right,
        top: imageRect.top,
        bottom: imageRect.bottom,
      },
      rhythm: layout.rhythm.rowHeight,
    };
  }, articleId);

  assert.ok(report, `Expected rendered image/copy geometry for ${articleId}`);
  assert.ok(
    report.adjacentLineCount > 0,
    `Expected adjacent columns to keep flowing beside ${articleId} image; found no adjacent copy in image band`,
  );
});

Then("the {string} section should not show a responsive image inset", async function (articleId) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.equal(solverSection.image, null);
});

Then("the {string} section image should span between {int} and {int} columns", async function (articleId, minSpan, maxSpan) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  const actualSpan = solverSection.image?.columnSpan;
  assert.ok(
    actualSpan >= minSpan && actualSpan <= maxSpan,
    `Expected ${articleId} image span between ${minSpan} and ${maxSpan}; found ${actualSpan}`,
  );
});

Then("the {string} section image should be centered at the top", async function (articleId) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.ok(solverSection.image, `Expected solved image for ${articleId}`);
  const expectedColumnStart = Math.floor((solverSection.columnCount - solverSection.image.columnSpan) / 2);
  assert.equal(
    solverSection.image.columnStart,
    expectedColumnStart,
    `Expected ${articleId} image to start at centered column ${expectedColumnStart}; found ${solverSection.image.columnStart}`,
  );
  assert.equal(solverSection.image.y, 0, `Expected ${articleId} image to start at the top of its body frame`);
});

Then("the {string} section image should be right aligned at the top", async function (articleId) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.ok(solverSection.image, `Expected solved image for ${articleId}`);
  const expectedColumnStart = solverSection.columnCount - solverSection.image.columnSpan;
  assert.equal(
    solverSection.image.columnStart,
    expectedColumnStart,
    `Expected ${articleId} image to start at rightmost column ${expectedColumnStart}; found ${solverSection.image.columnStart}`,
  );
  assert.equal(solverSection.image.y, 0, `Expected ${articleId} image to start at the top of its body frame`);
});

Then("the {string} continuation should not repeat front-page images", async function (articleId) {
  const report = await requirePage(this).evaluate((targetArticleId) => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const activePageNumber = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const frontBlock = layout?.pages.find((page) => page.pageNumber === 1)?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    const activeBlock = layout?.pages.find((page) => page.pageNumber === activePageNumber)?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    const imageAssetIds = (block) => (block?.furniture ?? [])
      .filter((item) => item.kind === "image")
      .map((item) => item.assetId);
    return {
      frontImageAssetIds: imageAssetIds(frontBlock),
      continuationImageAssetIds: imageAssetIds(activeBlock),
      continuationHasMore: activeBlock?.hasMore ?? null,
    };
  }, articleId);

  assert.ok(report.frontImageAssetIds.length > 0, `Expected ${articleId} to use an image on the front page`);
  const repeated = report.continuationImageAssetIds.filter((assetId) => report.frontImageAssetIds.includes(assetId));
  assert.deepEqual(repeated, [], `Expected ${articleId} continuation not to repeat front image assets`);
  assert.equal(report.continuationHasMore, false, `Expected ${articleId} continuation to exhaust the remaining article text`);
});

Then("the inside page header should center labels on the rhythm row", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    const layout = window.__PAPYRUS_LAYOUT__;
    const rhythm = layout?.rhythm?.rowHeight ?? 19;
    const header = active?.querySelector(".inside-header");
    const headerRect = header?.getBoundingClientRect();
    const labelRects = Array.from(header?.querySelectorAll("span") ?? []).map((label) => {
      const rect = label.getBoundingClientRect();
      return {
        text: label.textContent,
        top: rect.top,
        bottom: rect.bottom,
        height: rect.height,
      };
    });
    return {
      rhythm,
      header: headerRect && {
        top: headerRect.top,
        bottom: headerRect.bottom,
        height: headerRect.height,
      },
      labels: labelRects,
    };
  });

  assert.ok(report.header, "Expected inside page header geometry");
  assert.equal(report.labels.length, 3, "Expected inside header to render three labels");
  const expectedTop = report.header.top + report.rhythm;
  for (const label of report.labels) {
    assert.ok(
      Math.abs(label.top - expectedTop) <= 0.75,
      `Expected "${label.text}" to start on the centered rhythm row at ${expectedTop}; found ${label.top}`,
    );
    assert.ok(
      Math.abs(label.height - report.rhythm) <= 0.75,
      `Expected "${label.text}" to occupy one rhythm row; found ${label.height}`,
    );
  }
});

Then("continuation title chrome should be compact", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    const layout = window.__PAPYRUS_LAYOUT__;
    const rhythm = layout?.rhythm?.rowHeight ?? 19;
    const title = active?.querySelector(".continued-title");
    const body = active?.querySelector(".continuation-body");
    const headline = title?.querySelector("h2");
    const firstLine = body?.querySelector(".measured-line");
    const titleStyle = title ? getComputedStyle(title) : null;
    const bodyStyle = body ? getComputedStyle(body) : null;
    const rect = (element) => {
      if (!element) return null;
      const box = element.getBoundingClientRect();
      return {
        top: box.top,
        bottom: box.bottom,
        height: box.height,
      };
    };

    return {
      rhythm,
      titleBorderBottomWidth: titleStyle ? Number.parseFloat(titleStyle.borderBottomWidth) : null,
      titlePaddingBottom: titleStyle ? Number.parseFloat(titleStyle.paddingBottom) : null,
      bodyBorderTopWidth: bodyStyle ? Number.parseFloat(bodyStyle.borderTopWidth) : null,
      headlineRect: rect(headline),
      firstLineRect: rect(firstLine),
    };
  });

  assert.equal(report.titleBorderBottomWidth, 0, "Expected continuation title to render without a bottom h-rule");
  assert.equal(report.titlePaddingBottom, 0, "Expected continuation title to render without bottom padding");
  assert.equal(report.bodyBorderTopWidth, 0, "Expected continuation body not to render a top h-rule");
  assert.ok(report.headlineRect, "Expected continuation headline geometry");
  assert.ok(report.firstLineRect, "Expected first continuation copy line geometry");
  const headlineToCopyGap = report.firstLineRect.top - report.headlineRect.bottom;
  assert.ok(
    headlineToCopyGap <= report.rhythm + 0.75,
    `Expected continuation headline-to-copy gap to be at most one rhythm row; found ${headlineToCopyGap}`,
  );
});

Then("the {string} section image frame should preserve its aspect ratio", async function (articleId) {
  const report = await requirePage(this).evaluate((targetArticleId) => {
    const active = document.querySelector(".paper-page--active");
    const pageNumber = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const layout = window.__PAPYRUS_LAYOUT__;
    const rhythm = layout?.rhythm?.rowHeight ?? 19;
    const solvedPage = layout?.pages.find((candidate) => candidate.pageNumber === pageNumber);
    const block = solvedPage?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    const image = block?.furniture.find((item) => item.kind === "image") ?? null;
    const section = Array.from(active?.querySelectorAll(".solved-block--articleFrame") ?? [])
      .find((candidate) => candidate.getAttribute("data-article-id") === targetArticleId);
    const frame = section?.querySelector(".photo-frame") ?? null;
    const frameRect = frame?.getBoundingClientRect();
    return {
      rhythm,
      image: image && {
        width: image.width,
        imageHeight: image.imageHeight,
        aspectRatio: image.aspectRatio,
      },
      frame: frameRect && {
        width: frameRect.width,
        height: frameRect.height,
      },
    };
  }, articleId);

  assert.ok(report.image, `Expected solved image for ${articleId}`);
  assert.ok(report.frame, `Expected rendered image frame for ${articleId}`);
  const expectedHeight = report.image.width / report.image.aspectRatio;
  assert.ok(
    Math.abs(report.image.imageHeight - expectedHeight) <= report.rhythm + 0.75,
    `Expected ${articleId} solved image height to preserve aspect within one rhythm row; width=${report.image.width}, height=${report.image.imageHeight}, aspect=${report.image.aspectRatio}`,
  );
  assert.ok(
    Math.abs(report.frame.height - report.image.imageHeight) <= 0.75,
    `Expected ${articleId} rendered frame height ${report.frame.height} to match solved image height ${report.image.imageHeight}`,
  );
  assert.ok(
    Math.abs(report.frame.width - report.image.width) <= 0.75,
    `Expected ${articleId} rendered frame width ${report.frame.width} to match solved image width ${report.image.width}`,
  );
});

Then("the front article {string} should use the requested slot composition", async function (articleId) {
  const block = await getSolvedSection(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  assert.equal(block.pageNumber, 1);
  assert.equal(block.columnCount, 4);

  const image = block.image;
  assert.ok(image, `Expected ${articleId} to have a front image`);
  assert.equal(image.columnStart, 2);
  assert.equal(image.columnSpan, 2);

  const headline = block.chromeBoxes?.find((box) => box.slot === "headline");
  const deck = block.chromeBoxes?.find((box) => box.slot === "deck");
  const byline = block.chromeBoxes?.find((box) => box.slot === "byline");
  assert.ok(headline, "Expected composed headline chrome box");
  assert.ok(deck, "Expected composed deck chrome box");
  assert.ok(byline, "Expected composed byline chrome box");
  assert.equal(headline.columnStart, 0);
  assert.equal(headline.columnSpan, 2);
  assert.equal(deck.columnStart, 0);
  assert.equal(deck.columnSpan, 2);
  assert.equal(byline.columnStart, 0);
  assert.equal(byline.columnSpan, 2);

  const imageFrameHeight = image.imageHeight ?? image.height;
  const naturalImageHeight = image.width / image.aspectRatio;
  const imageRhythm = image.captionLineHeight ?? image.captionHeight ?? 19;
  assert.ok(
    imageFrameHeight >= naturalImageHeight - 0.75,
    `Expected image frame height ${imageFrameHeight}px to allow full-width image height ${naturalImageHeight}px`,
  );
  assert.ok(
    imageFrameHeight < naturalImageHeight + imageRhythm + 0.75,
    `Expected image frame height ${imageFrameHeight}px to stay within one rhythm row of natural height ${naturalImageHeight}px`,
  );
  assert.ok(image.caption, `Expected ${articleId} front image to expose a caption`);

  const renderedImageTop = await requirePage(this).evaluate((targetArticleId) => {
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    const imageElement = story?.querySelector(".lead-photo");
    if (!story || !imageElement) return null;
    const storyRect = story.getBoundingClientRect();
    const imageRect = imageElement.getBoundingClientRect();
    return imageRect.top - storyRect.top;
  }, articleId);
  assert.ok(renderedImageTop !== null, `Expected rendered front image for ${articleId}`);
  assert.ok(Math.abs(renderedImageTop) <= 0.75, `Expected rendered image to start at article top; found ${renderedImageTop}`);

  const imageCopyGap = await requirePage(this).evaluate((targetArticleId) => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    const imageElement = story?.querySelector(".lead-photo");
    if (!layout || !story || !imageElement) return null;
    const imageRect = imageElement.getBoundingClientRect();
    const overlappingLines = Array.from(story.querySelectorAll(".measured-line"))
      .map((line) => line.getBoundingClientRect())
      .filter((lineRect) => (
        lineRect.left < imageRect.right - 0.75 &&
        lineRect.right > imageRect.left + 0.75 &&
        lineRect.top >= imageRect.bottom - 0.75
      ))
      .sort((first, second) => first.top - second.top);
    return {
      gap: overlappingLines[0] ? overlappingLines[0].top - imageRect.bottom : null,
      rhythm: layout.rhythm.rowHeight,
    };
  }, articleId);
  assert.ok(imageCopyGap, `Expected rendered image/copy geometry for ${articleId}`);
  assert.ok(imageCopyGap.gap !== null, `Expected copy below the image inset for ${articleId}`);
  assert.ok(
    imageCopyGap.gap >= imageCopyGap.rhythm - 0.75,
    `Expected one rhythm row between image and copy; found ${imageCopyGap.gap}px with rhythm ${imageCopyGap.rhythm}px`,
  );

  const renderedCaption = await requirePage(this).evaluate((targetArticleId) => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    const pageNumber = Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const block = layout?.pages.find((candidate) => candidate.pageNumber === pageNumber)?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    const image = block?.furniture.find((item) => item.kind === "image") ?? null;
    const caption = story?.querySelector(".lead-photo figcaption");
    if (!layout || !caption) return null;
    const rect = caption.getBoundingClientRect();
    const style = window.getComputedStyle(caption);
    return {
      text: caption.textContent,
      height: rect.height,
      solvedHeight: image?.captionHeight ?? null,
      fontSize: Number.parseFloat(style.fontSize),
      lineHeight: Number.parseFloat(style.lineHeight),
      fontStyle: style.fontStyle,
      rhythm: layout.rhythm.rowHeight,
    };
  }, articleId);
  assert.ok(renderedCaption, `Expected rendered caption for ${articleId}`);
  assert.equal(renderedCaption.text, image.caption);
  assert.equal(renderedCaption.height, renderedCaption.solvedHeight);
  assert.ok(renderedCaption.height >= renderedCaption.rhythm);
  assert.equal(renderedCaption.lineHeight, renderedCaption.rhythm);
  assert.equal(renderedCaption.fontStyle, "italic");
  assert.ok(
    renderedCaption.fontSize < block.columns[0][0].fontSize,
    `Expected caption font ${renderedCaption.fontSize}px to be smaller than body font ${block.columns[0][0].fontSize}px`,
  );
});

Then("the {string} section image caption should render completely", async function (articleId) {
  const report = await requirePage(this).evaluate((targetArticleId) => {
    const active = document.querySelector(".paper-page--active");
    const pageNumber = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const layout = window.__PAPYRUS_LAYOUT__;
    const solvedPage = layout?.pages.find((candidate) => candidate.pageNumber === pageNumber);
    const block = solvedPage?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    const image = block?.furniture.find((item) => item.kind === "image") ?? null;
    const section = Array.from(active?.querySelectorAll(".solved-block--articleFrame") ?? [])
      .find((candidate) => candidate.getAttribute("data-article-id") === targetArticleId);
    const caption = section?.querySelector(".continuation-photo figcaption, .lead-photo figcaption") ?? null;
    if (!layout || !image || !caption) return null;
    const rect = caption.getBoundingClientRect();
    const style = window.getComputedStyle(caption);
    return {
      text: caption.textContent,
      solvedText: image.caption,
      height: rect.height,
      solvedHeight: image.captionHeight,
      lineHeight: Number.parseFloat(style.lineHeight),
      scrollHeight: caption.scrollHeight,
      clientHeight: caption.clientHeight,
      whiteSpace: style.whiteSpace,
      overflowY: style.overflowY,
      rhythm: layout.rhythm.rowHeight,
    };
  }, articleId);

  assert.ok(report, `Expected rendered caption geometry for ${articleId}`);
  assert.equal(report.text, report.solvedText);
  assert.equal(report.height, report.solvedHeight);
  assert.equal(report.lineHeight, report.rhythm);
  assert.ok(report.height > report.rhythm, `Expected long caption to reserve multiple rhythm rows; found ${report.height}`);
  assert.ok(
    report.scrollHeight <= report.clientHeight + 1,
    `Expected caption not to clip; scrollHeight=${report.scrollHeight}, clientHeight=${report.clientHeight}`,
  );
  assert.notEqual(report.whiteSpace, "nowrap");
  assert.notEqual(report.overflowY, "hidden");
});

Then("image captions should have no background", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    return Array.from(active?.querySelectorAll(".lead-photo figcaption, .front-prelude-photo figcaption, .continuation-photo figcaption, .article-photo figcaption") ?? [])
      .map((caption) => {
        const style = window.getComputedStyle(caption);
        return {
          text: caption.textContent,
          backgroundColor: style.backgroundColor,
          backgroundImage: style.backgroundImage,
        };
      });
  });

  assert.ok(report.length > 0, "Expected at least one rendered image caption");
  for (const caption of report) {
    assert.match(
      caption.backgroundColor,
      /rgba?\(0,\s*0,\s*0(?:,\s*0)?\)|transparent/,
      `Expected image caption background to be transparent; found ${caption.backgroundColor} for "${caption.text}"`,
    );
    assert.equal(caption.backgroundImage, "none", `Expected image caption background image to be none for "${caption.text}"`);
  }
});

Then("the first three front stories should not reserve top rules", async function () {
  const frontChrome = await requirePage(this).evaluate(() => {
    const frontPage = window.__PAPYRUS_LAYOUT__?.pages.find((candidate) => candidate.pageNumber === 1);
    return frontPage?.regions
      .flatMap((region) => region.blocks)
      .filter((block) => block.type === "articleFrame")
      .slice(0, 3)
      .map((block) => ({
        articleId: block.article?.slug ?? block.id,
        borderTopHeight: block.front?.chrome?.borderTopHeight ?? null,
        paddingTop: block.front?.chrome?.paddingTop ?? null,
      })) ?? [];
  });
  assert.equal(frontChrome.length, 3, `Expected three front stories; found ${frontChrome.length}`);
  for (const story of frontChrome) {
    assert.equal(story.borderTopHeight, 0, `Expected ${story.articleId} not to reserve a top rule`);
    assert.equal(story.paddingTop, 0, `Expected ${story.articleId} not to reserve top padding`);
  }
});

Then("front jump labels should use upper-row rhythm without h-rules", async function () {
  const jumpReport = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const frontPage = layout?.pages.find((candidate) => candidate.pageNumber === 1);
    const rhythm = layout?.rhythm?.rowHeight ?? 19;
    const stories = frontPage?.regions
      .flatMap((region) => region.blocks)
      .filter((block) => block.type === "articleFrame" && block.jumpTargetPage)
      .map((block) => {
        const articleId = block.article?.slug ?? block.id;
        const jump = document.querySelector(`.front-story[data-article-id="${articleId}"] .jump-line`);
        const style = jump ? window.getComputedStyle(jump) : null;
        const rect = jump?.getBoundingClientRect();
        return {
          articleId,
          solvedBorderTopHeight: block.front?.chrome?.jumpBorderTopHeight ?? null,
          solvedPaddingTop: block.front?.chrome?.jumpPaddingTop ?? null,
          solvedPaddingBottom: block.front?.chrome?.jumpPaddingBottom ?? null,
          solvedReserveHeight: block.front?.jumpReserveHeight ?? null,
          renderedBorderTopWidth: style ? Number.parseFloat(style.borderTopWidth) : null,
          renderedPaddingTop: style ? Number.parseFloat(style.paddingTop) : null,
          renderedPaddingBottom: style ? Number.parseFloat(style.paddingBottom) : null,
          renderedHeight: rect?.height ?? null,
          rhythm,
        };
      }) ?? [];
    return { rhythm, stories };
  });
  assert.ok(jumpReport.stories.length > 0, "Expected front jump labels");
  for (const story of jumpReport.stories) {
    assert.equal(story.solvedBorderTopHeight, 0, `Expected ${story.articleId} jump label not to reserve an h-rule`);
    assert.equal(story.solvedPaddingTop, 0, `Expected ${story.articleId} jump label not to reserve top padding`);
    assert.equal(story.solvedPaddingBottom, jumpReport.rhythm, `Expected ${story.articleId} jump label to reserve one bottom rhythm row`);
    assert.equal(story.solvedReserveHeight, jumpReport.rhythm * 2, `Expected ${story.articleId} jump label reserve to stay two rhythm rows`);
    assert.equal(story.renderedBorderTopWidth, 0, `Expected ${story.articleId} jump label h-rule not to render`);
    assert.equal(story.renderedPaddingTop, 0, `Expected ${story.articleId} jump label rendered top padding to be zero`);
    assert.equal(story.renderedPaddingBottom, jumpReport.rhythm, `Expected ${story.articleId} jump label rendered bottom padding to be one rhythm row`);
    assert.ok(story.renderedHeight !== null, `Expected rendered jump label for ${story.articleId}`);
    assert.ok(
      Math.abs(story.renderedHeight - jumpReport.rhythm * 2) <= 0.75,
      `Expected ${story.articleId} jump label to render at two rhythm rows; found ${story.renderedHeight}`,
    );
  }
});

Then("the front article {string} should share one copy band below lead furniture", async function (articleId) {
  const block = await getSolvedSection(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  assert.ok(block.front?.composition, `Expected composed front block for ${articleId}`);
  assert.equal(block.hasMore, true, `Expected ${articleId} front teaser to continue`);
  assert.ok(block.image, `Expected ${articleId} to have a solved image`);

  const copyBandTops = block.front.composition.copyBandTops;
  assert.ok(Array.isArray(copyBandTops), `Expected ${articleId} to expose solved per-column copy bands`);
  const solvedFirstLineYs = block.columns.map((column) => column[0]?.y ?? null);
  assert.ok(solvedFirstLineYs.every((lineY) => lineY !== null), `Expected every ${articleId} column to contain copy`);
  assert.deepEqual(solvedFirstLineYs, copyBandTops);
  assert.ok(
    solvedFirstLineYs.every((lineY) => lineY === solvedFirstLineYs[0]),
    `Expected all composed columns to share one solved copy band; found ${solvedFirstLineYs.join(", ")}`,
  );
  const solvedLineCounts = block.columns.map((column) => column.length);
  assert.ok(
    solvedLineCounts.every((lineCount) => lineCount === solvedLineCounts[0]),
    `Expected all composed columns to have the same solved line count; found ${solvedLineCounts.join(", ")}`,
  );

  const renderedFirstLineTops = await requirePage(this).evaluate((targetArticleId) => {
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    if (!story) return null;
    const image = story.querySelector(".lead-photo");
    const imageRect = image?.getBoundingClientRect();
    return Array.from(story.querySelectorAll(".story-composition-column")).map((column) => {
      const firstLine = column.querySelector(".measured-line");
      if (!firstLine) return null;
      const storyRect = story.getBoundingClientRect();
      const lineRect = firstLine.getBoundingClientRect();
      return {
        top: lineRect.top - storyRect.top,
        imageBottom: imageRect ? imageRect.bottom - storyRect.top : null,
      };
    });
  }, articleId);
  assert.ok(renderedFirstLineTops, `Expected rendered columns for ${articleId}`);
  assert.ok(renderedFirstLineTops.every((lineTop) => lineTop !== null), `Expected every rendered ${articleId} column to contain copy`);
  const renderedImageBottom = renderedFirstLineTops[0].imageBottom;
  assert.ok(renderedImageBottom !== null, `Expected rendered image for ${articleId}`);
  const renderedTops = renderedFirstLineTops.map((line) => line.top);
  assert.ok(
    renderedTops.every((lineTop) => Math.abs(lineTop - renderedTops[0]) <= 0.75),
    `Expected all rendered composed columns to share one copy band; found ${renderedTops.join(", ")}`,
  );
  assert.ok(
    renderedTops.every((lineTop) => lineTop >= renderedImageBottom - 0.75),
    `Expected rendered copy band to clear lead furniture; found ${renderedTops.join(", ")} with image bottom ${renderedImageBottom}`,
  );
});

Then("the front page should resolve headline scale {string} for article {string}", async function (expectedScale, articleId) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  assert.equal(block.headlineScale, expectedScale);
});

Then("the front page should resolve editorial priority {string} for article {string}", async function (expectedPriority, articleId) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  assert.equal(block.editorialPriority, expectedPriority);
});

Then("the first front story should be article {string}", async function (expectedArticleId) {
  const firstArticleId = await requirePage(this).evaluate(() => {
    const frontPage = window.__PAPYRUS_LAYOUT__?.pages.find((candidate) => candidate.pageNumber === 1);
    return frontPage?.regions
      .flatMap((region) => region.blocks)
      .find((block) => block.type === "articleFrame")?.article?.slug ?? null;
  });
  assert.equal(firstArticleId, expectedArticleId);
});

Then("front article {string} should occupy row {int} columns {int} through {int}", async function (articleId, rowStart, columnStart, columnEnd) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  const placement = block.front?.gridPlacement;
  assert.ok(placement, `Expected ${articleId} to use solved front grid placement`);
  assert.equal(placement.rowStart + 1, rowStart);
  assert.equal(placement.columnStart + 1, columnStart);
  assert.equal(placement.columnStart + placement.columnSpan, columnEnd);

  const renderedPlacement = await requirePage(this).evaluate((targetArticleId) => {
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    if (!story) return null;
    const style = getComputedStyle(story);
    return {
      gridColumnStart: style.gridColumnStart,
      gridColumnEnd: style.gridColumnEnd,
      gridRowStart: style.gridRowStart,
      gridRowEnd: style.gridRowEnd,
    };
  }, articleId);
  assert.ok(renderedPlacement, `Expected rendered front story for ${articleId}`);
  assert.equal(renderedPlacement.gridColumnStart, String(columnStart));
  assert.equal(renderedPlacement.gridColumnEnd, `span ${columnEnd - columnStart + 1}`);
  assert.equal(renderedPlacement.gridRowStart, String(rowStart));
  assert.equal(renderedPlacement.gridRowEnd, `span ${placement.rowSpan}`);
});

Then("the front page should render article {string}", async function (articleId) {
  const rendered = await requirePage(this).locator(`.front-story[data-article-id="${articleId}"]`).count();
  assert.ok(rendered > 0, `Expected rendered front story for ${articleId}`);
});

Then("the front page should render a newspaper footer", async function () {
  const report = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const frontPage = layout?.pages.find((page) => page.pageNumber === 1);
    const footer = document.querySelector("#page-1 .front-footer");
    if (!layout || !frontPage || !frontPage.frontFooter || !footer) return null;
    const footerRect = footer.getBoundingClientRect();
    const computed = getComputedStyle(footer);
    return {
      solvedHeight: frontPage.frontFooter.height,
      solvedMarginTop: frontPage.frontFooter.marginTop,
      renderedHeight: footerRect.height,
      renderedMarginTop: Number.parseFloat(computed.marginTop),
      rowHeight: frontPage.frontFooter.rowHeight,
      utilityCount: frontPage.frontFooter.utilityEntries.length,
    };
  });
  assert.ok(report, "Expected solved and rendered front footer");
  assert.ok(Math.abs(report.renderedHeight - report.solvedHeight) <= 0.75, `Expected rendered footer height ${report.renderedHeight} to match solved ${report.solvedHeight}`);
  assert.ok(Math.abs(report.renderedMarginTop - report.solvedMarginTop) <= 0.75, `Expected rendered footer margin ${report.renderedMarginTop} to match solved ${report.solvedMarginTop}`);
  assert.equal(report.utilityCount, 4);
  assert.ok(report.solvedHeight >= report.rowHeight * 2, `Expected footer to reserve at least two rhythm rows; found ${report.solvedHeight}`);
});

Then("the front page footer should list edition sections", async function () {
  const report = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const frontPage = layout?.pages.find((page) => page.pageNumber === 1);
    if (!frontPage?.frontFooter) return null;
    const expected = frontPage.frontFooter.entries.map((entry) => ({
      section: entry.section,
      articleSlug: entry.articleSlug,
      articleTitle: entry.articleTitle,
    }));
    const rendered = Array.from(document.querySelectorAll("#page-1 .front-footer__section-link")).map((link) => ({
      section: link.getAttribute("data-footer-section"),
      text: link.textContent?.replace(/\s+/g, " ").trim(),
      href: link.getAttribute("href"),
    }));
    return { expected, rendered };
  });
  assert.ok(report, "Expected solved front footer entries");
  assert.ok(report.expected.length > 0, "Expected at least one solved footer section");
  assert.equal(report.rendered.length, report.expected.length);
  for (const [index, expected] of report.expected.entries()) {
    const rendered = report.rendered[index];
    assert.equal(rendered.section, expected.section);
    assert.ok(rendered.text.includes(expected.section), `Expected rendered footer text to include section ${expected.section}`);
    assert.ok(rendered.text.includes(expected.articleTitle), `Expected rendered footer text to include title ${expected.articleTitle}`);
    assert.ok(rendered.href.endsWith(`#${expected.articleSlug}`), `Expected footer href ${rendered.href} to target #${expected.articleSlug}`);
  }
});

Then("the front page solved height should include footer rhythm space", async function () {
  const report = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const frontPage = layout?.pages.find((page) => page.pageNumber === 1);
    const region = frontPage?.regions[0];
    const footer = frontPage?.frontFooter;
    const footerElement = document.querySelector("#page-1 .front-footer");
    const gridElement = document.querySelector("#page-1 .front-grid");
    const contentElement = document.querySelector("#page-1 .paper-page-content");
    if (!layout || !frontPage || !region || !footer || !footerElement || !gridElement || !contentElement) return null;
    const rhythm = layout.rhythm.rowHeight;
    const solvedExpectedHeight =
      layout.pageChrome.pagePaddingTop +
      layout.pageChrome.mastheadHeight +
      layout.pageChrome.frontGridMarginTop +
      region.height +
      footer.marginTop +
      footer.height +
      layout.pageChrome.pagePaddingBottom;
    const gridRect = gridElement.getBoundingClientRect();
    const footerRect = footerElement.getBoundingClientRect();
    const contentRect = contentElement.getBoundingClientRect();
    return {
      rhythm,
      solvedPageHeight: frontPage.height,
      solvedExpectedHeight,
      renderedPageHeight: contentRect.height,
      renderedFooterGap: footerRect.top - gridRect.bottom,
      renderedFooterHeight: footerRect.height,
      solvedFooterMarginTop: footer.marginTop,
      solvedFooterHeight: footer.height,
    };
  });
  assert.ok(report, "Expected front footer height report");
  assert.ok(Math.abs(report.solvedPageHeight - report.solvedExpectedHeight) <= 0.75, `Expected solved page height ${report.solvedPageHeight} to include footer ${report.solvedExpectedHeight}`);
  assert.ok(Math.abs(report.renderedPageHeight - report.solvedPageHeight) <= 0.75, `Expected rendered page height ${report.renderedPageHeight} to match solved ${report.solvedPageHeight}`);
  assert.ok(Math.abs(report.renderedFooterGap - report.solvedFooterMarginTop) <= 0.75, `Expected footer gap ${report.renderedFooterGap} to match solved ${report.solvedFooterMarginTop}`);
  assert.ok(Math.abs(report.renderedFooterHeight - report.solvedFooterHeight) <= 0.75, `Expected footer height ${report.renderedFooterHeight} to match solved ${report.solvedFooterHeight}`);
  assert.equal(report.solvedPageHeight % report.rhythm, 0);
  assert.equal(report.solvedFooterMarginTop % report.rhythm, 0);
  assert.equal(report.solvedFooterHeight % report.rhythm, 0);
});

Then("the front page footer should fit within the solved page", async function () {
  const report = await requirePage(this).evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const frontPage = layout?.pages.find((page) => page.pageNumber === 1);
    const region = frontPage?.regions[0];
    const footer = frontPage?.frontFooter;
    const footerElement = document.querySelector("#page-1 .front-footer");
    const gridElement = document.querySelector("#page-1 .front-grid");
    const contentElement = document.querySelector("#page-1 .paper-page-content");
    if (!layout || !frontPage || !region || !footer || !footerElement || !gridElement || !contentElement) return null;
    const rhythm = layout.rhythm.rowHeight;
    const gridRect = gridElement.getBoundingClientRect();
    const footerRect = footerElement.getBoundingClientRect();
    const contentRect = contentElement.getBoundingClientRect();
    const rowHeights = region.rowHeights ?? [];
    const solvedGridHeight = rowHeights.reduce((total, height) => total + height, 0) + layout.rowGap * Math.max(0, rowHeights.length - 1);
    const unplacedBlockIds = region.blocks
      .filter((block) => !block.front?.gridPlacement)
      .map((block) => block.id);
    const maxPlacedRow = region.blocks.reduce((maxRow, block) => {
      const placement = block.front?.gridPlacement;
      return placement ? Math.max(maxRow, placement.rowStart + placement.rowSpan) : maxRow;
    }, 0);
    const stories = Array.from(gridElement.querySelectorAll(".front-story")).map((story, index) => {
      const rect = story.getBoundingClientRect();
      return {
        blockId: region.blocks[index]?.id,
        bottom: rect.bottom,
        bottomOverflow: rect.bottom - gridRect.bottom,
      };
    });
    const maxStoryBottom = stories.reduce((bottom, story) => Math.max(bottom, story.bottom), gridRect.top);
    const overflowingStories = stories
      .filter((story) => story.bottomOverflow > 0.75)
      .map((story) => ({ blockId: story.blockId, overflow: story.bottomOverflow }));
    return {
      rhythm,
      rowTrackCount: rowHeights.length,
      maxPlacedRow,
      unplacedBlockIds,
      overflowingStories,
      solvedGridHeight,
      solvedRegionHeight: region.height,
      solvedPageHeight: frontPage.height,
      renderedPageHeight: contentRect.height,
      renderedGridHeight: gridRect.height,
      renderedFooterGap: footerRect.top - gridRect.bottom,
      renderedFooterGapFromLastStory: footerRect.top - maxStoryBottom,
      renderedFooterHeight: footerRect.height,
      footerBottomInset: contentRect.bottom - footerRect.bottom,
      pagePaddingBottom: layout.pageChrome.pagePaddingBottom,
      solvedFooterMarginTop: footer.marginTop,
      solvedFooterHeight: footer.height,
    };
  });
  assert.ok(report, "Expected front footer fit report");
  assert.ok(report.rowTrackCount > 0, "Expected solved front grid row tracks");
  assert.deepEqual(report.unplacedBlockIds, [], "Expected every front story to have solver-owned grid placement");
  assert.ok(report.rowTrackCount >= report.maxPlacedRow, `Expected ${report.rowTrackCount} row tracks to cover placed row ${report.maxPlacedRow}`);
  assert.deepEqual(report.overflowingStories, [], "Expected all front stories to fit within the solved front grid");
  assert.ok(Math.abs(report.solvedGridHeight - report.solvedRegionHeight) <= 0.75, `Expected solved row tracks ${report.solvedGridHeight} to match region height ${report.solvedRegionHeight}`);
  assert.ok(Math.abs(report.renderedGridHeight - report.solvedRegionHeight) <= 0.75, `Expected rendered grid height ${report.renderedGridHeight} to match solved region height ${report.solvedRegionHeight}`);
  assert.ok(Math.abs(report.renderedFooterGap - report.solvedFooterMarginTop) <= 0.75, `Expected footer gap ${report.renderedFooterGap} to match solved margin ${report.solvedFooterMarginTop}`);
  assert.ok(report.renderedFooterGapFromLastStory + 0.75 >= report.solvedFooterMarginTop, `Expected footer to sit at least ${report.solvedFooterMarginTop}px below the last story; found ${report.renderedFooterGapFromLastStory}`);
  assert.ok(Math.abs(report.renderedFooterHeight - report.solvedFooterHeight) <= 0.75, `Expected footer height ${report.renderedFooterHeight} to match solved footer ${report.solvedFooterHeight}`);
  assert.ok(Math.abs(report.renderedPageHeight - report.solvedPageHeight) <= 0.75, `Expected rendered page height ${report.renderedPageHeight} to match solved page height ${report.solvedPageHeight}`);
  assert.ok(report.footerBottomInset + 0.75 >= report.pagePaddingBottom, `Expected footer to fit above bottom padding ${report.pagePaddingBottom}; found inset ${report.footerBottomInset}`);
  assert.equal(report.solvedPageHeight % report.rhythm, 0);
});

Then("the front page footer should stack utility links in the right column", async function () {
  const page = requirePage(this);
  const report = await page.evaluate(() => {
    const footer = document.querySelector("#page-1 .front-footer");
    const sections = footer?.querySelector(".front-footer__sections");
    const utilities = footer?.querySelector(".front-footer__utilities");
    if (!footer || !sections || !utilities) return null;
    const footerRect = footer.getBoundingClientRect();
    const sectionsRect = sections.getBoundingClientRect();
    const utilitiesRect = utilities.getBoundingClientRect();
    const entries = Array.from(footer.querySelectorAll("[data-footer-utility]")).map((entry) => ({
      id: entry.getAttribute("data-footer-utility"),
      text: entry.textContent?.trim(),
      role: entry.getAttribute("role"),
      ariaDisabled: entry.getAttribute("aria-disabled"),
      href: entry.getAttribute("href"),
      tagName: entry.tagName.toLowerCase(),
      rect: (() => {
        const rect = entry.getBoundingClientRect();
        return {
          bottom: rect.bottom,
          height: rect.height,
          left: rect.left,
          right: rect.right,
          top: rect.top,
        };
      })(),
    }));
    return {
      footerRight: footerRect.right,
      sectionsRight: sectionsRect.right,
      utilities: {
        bottom: utilitiesRect.bottom,
        left: utilitiesRect.left,
        right: utilitiesRect.right,
        top: utilitiesRect.top,
      },
      entries,
      rhythm: window.__PAPYRUS_LAYOUT__?.rhythm?.rowHeight ?? 19,
    };
  });
  assert.ok(report, "Expected footer utility report");
  const summary = report.entries.map(({ id, text, role, ariaDisabled, href, tagName }) => ({ id, text, role, ariaDisabled, href, tagName }));
  assert.deepEqual(summary, [
    { id: "archive", text: "Archive", role: null, ariaDisabled: null, href: "/archive", tagName: "a" },
    { id: "newsDesk", text: "Newsroom", role: null, ariaDisabled: null, href: "/newsroom", tagName: "a" },
    { id: "settings", text: "Settings", role: null, ariaDisabled: null, href: "/settings", tagName: "a" },
    { id: "login", text: "LOGIN", role: null, ariaDisabled: null, href: null, tagName: "span" },
  ]);
  assert.ok(report.utilities.left >= report.sectionsRight - 0.75, "Expected utility stack to sit to the right of section links");
  assert.ok(Math.abs(report.utilities.right - report.footerRight) <= 0.75, "Expected utility stack to end at the footer right edge");
  for (const entry of report.entries) {
    assert.ok(entry.rect.left >= report.utilities.left - 0.75, `Expected ${entry.id} to stay inside the utility column`);
    assert.ok(entry.rect.right <= report.utilities.right + 0.75, `Expected ${entry.id} to stay inside the utility column`);
    assert.ok(Math.abs(entry.rect.height - report.rhythm) <= 0.75, `Expected ${entry.id} to occupy one rhythm row`);
  }
  for (let index = 1; index < report.entries.length; index += 1) {
    const previous = report.entries[index - 1];
    const current = report.entries[index];
    assert.ok(current.rect.top >= previous.rect.bottom - 0.75, `Expected ${current.id} to stack below ${previous.id}`);
  }
});

Then("the archive masthead should say {string}", async function (expectedTitle) {
  const report = await requirePage(this).evaluate(() => ({
    title: document.querySelector(".archive-header h1")?.textContent?.trim() ?? "",
    hasFrontPagesText: document.querySelector(".archive-header")?.textContent?.includes("Front Pages") ?? false,
    description: document.querySelector("#archive-description")?.textContent?.trim() ?? "",
  }));
  assert.equal(report.title, expectedTitle);
  assert.equal(report.hasFrontPagesText, false);
  assert.match(report.description, /previous editions/i);
});

Then("the archive masthead should use the normal newspaper nameplate height", async function () {
  const report = await requirePage(this).evaluate(() => {
    const header = document.querySelector(".archive-header");
    const title = document.querySelector(".archive-header h1");
    const gridShell = document.querySelector(".archive-grid-shell");
    const grid = document.querySelector(".archive-grid");
    if (!header || !title || !gridShell || !grid) return null;
    const headerRect = header.getBoundingClientRect();
    const titleRect = title.getBoundingClientRect();
    const gridShellRect = gridShell.getBoundingClientRect();
    const gridRect = grid.getBoundingClientRect();
    const titleStyle = getComputedStyle(title);
    const rhythm = Number.parseFloat(getComputedStyle(header).getPropertyValue("--paper-rhythm"));
    return {
      rhythm,
      headerHeight: headerRect.height,
      titleTop: titleRect.top - headerRect.top,
      titleHeight: titleRect.height,
      titleMarginTop: Number.parseFloat(titleStyle.marginTop),
      titleMarginBottom: Number.parseFloat(titleStyle.marginBottom),
      fontSize: Number.parseFloat(titleStyle.fontSize),
      lineHeight: Number.parseFloat(titleStyle.lineHeight),
      gridShellGap: gridShellRect.top - headerRect.bottom,
      gridTopGap: gridRect.top - gridShellRect.top,
    };
  });
  assert.ok(report, "Expected archive masthead title");
  const expectedLineHeight = report.rhythm * 4;
  const expectedFontSize = expectedLineHeight * 1.3586956522;
  const expectedHalfRow = report.rhythm / 2;
  assert.ok(Math.abs(report.headerHeight - report.rhythm * 5) <= 0.75, `Expected archive header height ${report.headerHeight} to be five rhythm rows ${report.rhythm * 5}`);
  assert.ok(Math.abs(report.titleTop - expectedHalfRow) <= 0.75, `Expected archive title top ${report.titleTop} to be one half-row ${expectedHalfRow}`);
  assert.ok(Math.abs(report.titleHeight - expectedLineHeight) <= 0.75, `Expected archive title height ${report.titleHeight} to be four rows ${expectedLineHeight}`);
  assert.ok(Math.abs(report.titleMarginTop - expectedHalfRow) <= 0.75, `Expected archive title top margin ${report.titleMarginTop} to be one half-row ${expectedHalfRow}`);
  assert.ok(Math.abs(report.titleMarginBottom - expectedHalfRow) <= 0.75, `Expected archive title bottom margin ${report.titleMarginBottom} to be one half-row ${expectedHalfRow}`);
  assert.ok(Math.abs(report.lineHeight - expectedLineHeight) <= 0.75, `Expected archive line height ${report.lineHeight} to match normal masthead ${expectedLineHeight}`);
  assert.ok(Math.abs(report.fontSize - expectedFontSize) <= 0.75, `Expected archive font size ${report.fontSize} to match normal masthead ${expectedFontSize}`);
  assert.ok(Math.abs(report.gridShellGap) <= 0.75, `Expected archive gray substrate to start immediately below masthead; gap=${report.gridShellGap}`);
  assert.ok(Math.abs(report.gridTopGap - report.rhythm) <= 0.75, `Expected one empty gray row before archive previews; gap=${report.gridTopGap}`);
});

Then("the archive header should describe previous editions", async function () {
  const report = await requirePage(this).evaluate(() => {
    const description = document.querySelector("#archive-description");
    if (!description) return null;
    return {
      subtitle: description.textContent ?? "",
      visibleHeight: description.getBoundingClientRect().height,
    };
  });
  assert.ok(report, "Expected archive header report");
  const text = report.subtitle;
  assert.match(text ?? "", /previous editions/i);
  assert.doesNotMatch(text ?? "", /archive/i);
  assert.ok(report.visibleHeight <= 1, `Expected archive description to be visually hidden; height=${report.visibleHeight}`);
});

Then("the archive page should expose the shared rhythm overlay", async function () {
  const page = requirePage(this);
  const initialReport = await page.evaluate(() => {
    const shell = document.querySelector(".archive-rhythm-shell");
    if (!shell) return null;
    return {
      overlay: shell.getAttribute("data-rhythm-overlay"),
      rhythm: getComputedStyle(shell).getPropertyValue("--paper-rhythm").trim(),
    };
  });
  assert.ok(initialReport, "Expected archive rhythm shell");
  assert.equal(initialReport.overlay, "false");
  assert.equal(initialReport.rhythm, "19px");

  await page.keyboard.down("Control");
  await page.keyboard.press("=");
  await page.keyboard.up("Control");
  await page.waitForFunction(() => document.querySelector(".archive-rhythm-shell")?.getAttribute("data-rhythm-overlay") === "true");

  const overlayReport = await page.evaluate(() => {
    const shell = document.querySelector(".archive-rhythm-shell");
    if (!shell) return null;
    const pseudo = getComputedStyle(shell, "::before");
    return {
      overlay: shell.getAttribute("data-rhythm-overlay"),
      backgroundImage: pseudo.backgroundImage,
      position: pseudo.position,
    };
  });
  assert.ok(overlayReport, "Expected archive rhythm overlay report");
  assert.equal(overlayReport.overlay, "true");
  assert.equal(overlayReport.position, "absolute");
  assert.match(overlayReport.backgroundImage, /repeating-linear-gradient/);
});

Then("the archive layout should follow the archive rhythm", async function () {
  const report = await requirePage(this).evaluate(() => {
    const shell = document.querySelector(".archive-rhythm-shell");
    const header = document.querySelector(".archive-header");
    const gridShell = document.querySelector(".archive-grid-shell");
    const grid = document.querySelector(".archive-grid");
    const sentinel = document.querySelector(".archive-sentinel");
    if (!shell || !header || !gridShell || !grid || !sentinel) return null;
    const shellTop = shell.getBoundingClientRect().top;
    const rhythm = Number.parseFloat(getComputedStyle(shell).getPropertyValue("--paper-rhythm"));
    const rectFor = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: rect.top - shellTop,
        height: rect.height,
      };
    };
    return {
      rhythm,
      elements: [rectFor(header), rectFor(gridShell), rectFor(grid), rectFor(sentinel)],
    };
  });
  assert.ok(report, "Expected archive rhythm layout report");
  for (const element of report.elements) {
    assert.ok(isMultipleOfRhythm(element.top, report.rhythm), `Expected archive element top ${element.top} to align to ${report.rhythm}`);
    assert.ok(isMultipleOfRhythm(element.height, report.rhythm), `Expected archive element height ${element.height} to align to ${report.rhythm}`);
  }
});

Then("the archive should render front page preview cards", async function () {
  const page = requirePage(this);
  await page.waitForSelector(".archive-card", { state: "visible", timeout: 15_000 });
  const cardCount = await page.locator(".archive-card").count();
  assert.ok(cardCount > 0, "Expected at least one archive preview card");
});

Then("archive preview cards should be compact on the rhythm", async function () {
  const report = await requirePage(this).evaluate(() => {
    const shell = document.querySelector(".archive-rhythm-shell");
    const grid = document.querySelector(".archive-grid");
    const card = document.querySelector(".archive-card");
    const label = card?.querySelector(".archive-card__label");
    const preview = card?.querySelector(".archive-front-preview");
    if (!shell || !grid || !card || !label || !preview) return null;
    const rhythm = Number.parseFloat(getComputedStyle(shell).getPropertyValue("--paper-rhythm"));
    const cardStyle = getComputedStyle(card);
    const gridStyle = getComputedStyle(grid);
    const labelRect = label.getBoundingClientRect();
    const previewRect = preview.getBoundingClientRect();
    return {
      rhythm,
      gridGap: Number.parseFloat(gridStyle.rowGap),
      cardGap: Number.parseFloat(cardStyle.rowGap),
      cardPaddingTop: Number.parseFloat(cardStyle.paddingTop),
      labelHeight: labelRect.height,
      previewTopGap: previewRect.top - labelRect.bottom,
      previewHeight: previewRect.height,
    };
  });
  assert.ok(report, "Expected archive compact card report");
  assert.ok(Math.abs(report.gridGap - report.rhythm) <= 0.75, `Expected desktop archive grid gap ${report.gridGap} to be one rhythm row ${report.rhythm}`);
  assert.equal(report.cardGap, 0);
  assert.equal(report.cardPaddingTop, 0);
  assert.ok(Math.abs(report.labelHeight - report.rhythm) <= 0.75, `Expected archive label height ${report.labelHeight} to equal rhythm ${report.rhythm}`);
  assert.ok(Math.abs(report.previewTopGap) <= 0.75, `Expected preview to start directly below label; found ${report.previewTopGap}`);
  assert.ok(isMultipleOfRhythm(report.previewHeight, report.rhythm), `Expected preview height ${report.previewHeight} to be rhythm-aligned`);
});

Then("archive preview cards should link to canonical edition routes", async function () {
  const links = await requirePage(this).evaluate(() => (
    Array.from(document.querySelectorAll(".archive-card__hit-area")).map((link) => ({
      href: link.getAttribute("href"),
      label: link.getAttribute("aria-label"),
    }))
  ));
  assert.ok(links.length > 0, "Expected archive preview links");
  for (const link of links) {
    assert.ok(link.href, "Expected archive card href");
    assert.match(link.href, /^\/\d{4}\/[a-z]+\/\d{1,2}(?:\/)?$/);
    assert.ok(link.label?.startsWith("Open "), "Expected archive card link to have an accessible label");
  }
});

Then("archive previews should include masthead, front grid, and footer", async function () {
  const report = await requirePage(this).evaluate(() => {
    const previews = Array.from(document.querySelectorAll(".archive-front-preview"));
    return previews.map((preview) => ({
      hasMasthead: Boolean(preview.querySelector(".masthead")),
      hasFrontGrid: Boolean(preview.querySelector(".front-grid")),
      hasFooter: Boolean(preview.querySelector(".front-footer")),
      linkCount: preview.querySelectorAll("a").length,
    }));
  });
  assert.ok(report.length > 0, "Expected archive previews");
  for (const preview of report) {
    assert.equal(preview.hasMasthead, true);
    assert.equal(preview.hasFrontGrid, true);
    assert.equal(preview.hasFooter, true);
    assert.equal(preview.linkCount, 0, "Expected preview internals to render without active links");
  }
});

Then("the archive should use a paper header over a neutral gray grid substrate", async function () {
  const report = await requirePage(this).evaluate(() => {
    const page = document.querySelector(".archive-page");
    const header = document.querySelector(".archive-header");
    const gridShell = document.querySelector(".archive-grid-shell");
    const grid = document.querySelector(".archive-grid");
    if (!page || !header || !gridShell || !grid) return null;
    const gridShellRect = gridShell.getBoundingClientRect();
    const gridRect = grid.getBoundingClientRect();
    return {
      pageBackground: getComputedStyle(page).backgroundColor,
      gridBackground: getComputedStyle(gridShell).backgroundColor,
      headerBackgroundImage: getComputedStyle(header).backgroundImage,
      rhythm: Number.parseFloat(getComputedStyle(page).getPropertyValue("--paper-rhythm")),
      gridTopGap: gridRect.top - gridShellRect.top,
    };
  });
  assert.ok(report, "Expected archive substrate report");
  assert.equal(report.pageBackground, "rgb(128, 128, 128)");
  assert.equal(report.gridBackground, "rgb(128, 128, 128)");
  assert.notEqual(report.headerBackgroundImage, "none", "Expected archive masthead area to keep the paper texture");
  assert.ok(Math.abs(report.gridTopGap - report.rhythm) <= 0.75, `Expected one empty gray rhythm row before archive previews; found ${report.gridTopGap}px`);
});

Then("the archive should render a two-column front page grid", async function () {
  const columns = await requirePage(this).evaluate(() => {
    const grid = document.querySelector(".archive-grid");
    if (!grid) return 0;
    return getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean).length;
  });
  assert.equal(columns, 2);
});

Then("the archive API should cap requested batches at {int}", async function (expectedLimit) {
  const report = await requirePage(this).evaluate(async () => {
    const response = await fetch("/api/archive/editions?limit=500");
    const payload = await response.json();
    return {
      ok: response.ok,
      previewCount: Array.isArray(payload.previews) ? payload.previews.length : -1,
    };
  });
  assert.equal(report.ok, true);
  assert.ok(report.previewCount <= expectedLimit, `Expected capped archive batch to be <= ${expectedLimit}; found ${report.previewCount}`);
});

Then("the archive sentinel should load another batch when more editions exist", async function () {
  const page = requirePage(this);
  const sentinel = page.locator("[data-archive-sentinel]").first();
  const hasNextCursor = await sentinel.getAttribute("data-has-next-cursor");
  if (hasNextCursor !== "true") {
    assert.match((await sentinel.textContent()) ?? "", /End of archive/i);
    return;
  }

  const initialCount = await page.locator(".archive-card").count();
  await sentinel.scrollIntoViewIfNeeded();
  await page.waitForFunction(
    (count) => document.querySelectorAll(".archive-card").length > count,
    initialCount,
    { timeout: 15_000 },
  );
  const ids = await page.evaluate(() => Array.from(document.querySelectorAll(".archive-card")).map((card) => card.getAttribute("data-archive-edition-id")));
  assert.equal(new Set(ids).size, ids.length, "Expected archive lazy loading to avoid duplicate edition cards");
});

Then("the active page should not render a front page footer", async function () {
  const footerCount = await requirePage(this).locator(".paper-page--active .front-footer").count();
  assert.equal(footerCount, 0);
});

Then("the front article {string} should inset its image in the top right half", async function (articleId) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  const image = block.furniture.find((item) => item.kind === "image");
  assert.ok(image, `Expected ${articleId} to have solved image furniture`);
  assert.equal(image.columnStart + image.columnSpan, block.columnCount);
  assert.ok(
    image.columnStart >= Math.floor(block.columnCount / 2),
    `Expected image to start in right half for ${block.columnCount} columns; found column ${image.columnStart + 1}`,
  );
  assert.ok(
    image.columnSpan <= Math.ceil(block.columnCount / 2),
    `Expected image to stay within right half for ${block.columnCount} columns; found span ${image.columnSpan}`,
  );
  assert.equal(image.y, 0);

  const rendered = await requirePage(this).evaluate((targetArticleId) => {
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    const imageElement = story?.querySelector(".lead-photo");
    if (!story || !imageElement) return null;
    const storyRect = story.getBoundingClientRect();
    const imageRect = imageElement.getBoundingClientRect();
    return {
      left: imageRect.left - storyRect.left,
      top: imageRect.top - storyRect.top,
      width: imageRect.width,
      storyWidth: storyRect.width,
    };
  }, articleId);
  assert.ok(rendered, `Expected rendered image for ${articleId}`);
  assert.ok(rendered.top <= 0.75, `Expected rendered image top to align with article top; found ${rendered.top}`);
  assert.ok(
    rendered.left + rendered.width / 2 >= rendered.storyWidth / 2 - 1,
    `Expected rendered image center in right half; found left ${rendered.left} width ${rendered.width}`,
  );
  assert.ok(
    Math.abs(rendered.left + rendered.width - rendered.storyWidth) <= 1,
    `Expected rendered image to align with the article right edge; found right ${rendered.left + rendered.width} of ${rendered.storyWidth}`,
  );
});

Then("the front article {string} should stack its headline above the three-column media inset", async function (articleId) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  assert.equal(block.columnCount, 3);
  assert.equal(block.front?.composition?.mode, "titleStackedMedia");
  const image = block.furniture.find((item) => item.kind === "image");
  assert.ok(image, `Expected ${articleId} to have solved image furniture`);
  assert.equal(image.columnStart, 1);
  assert.equal(image.columnSpan, 2);
  const titleBoxes = (block.chromeBoxes ?? []).filter((box) => box.slot === "label" || box.slot === "headline");
  const headline = titleBoxes.find((box) => box.slot === "headline");
  const deck = (block.chromeBoxes ?? []).find((box) => box.slot === "deck");
  assert.ok(headline, `Expected ${articleId} to have a solved headline box`);
  assert.ok(deck, `Expected ${articleId} to have a solved deck box`);
  const titleBottom = Math.max(...titleBoxes.map((box) => box.y + box.height));
  assert.equal(headline.columnStart, 0);
  assert.equal(headline.columnSpan, 3);
  assert.ok(image.y >= titleBottom, `Expected image y ${image.y} to clear title bottom ${titleBottom}`);
  assert.equal(deck.columnStart, 0);
  assert.ok(deck.columnSpan <= image.columnStart, `Expected deck span ${deck.columnSpan} to stay left of image start ${image.columnStart}`);
  assert.ok(deck.y >= image.y - 0.75, `Expected deck y ${deck.y} to align with image top ${image.y}`);
  assert.ok(deck.y < image.y + image.height, `Expected deck y ${deck.y} to float beside image ending at ${image.y + image.height}`);

  const rendered = await requirePage(this).evaluate((targetArticleId) => {
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    const headlineElement = story?.querySelector('[data-chrome-slot="headline"]');
    const deckElement = story?.querySelector('[data-chrome-slot="deck"]');
    const imageElement = story?.querySelector(".lead-photo");
    if (!story || !headlineElement || !deckElement || !imageElement) return null;
    const storyRect = story.getBoundingClientRect();
    const toRelativeRect = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left - storyRect.left,
        right: rect.right - storyRect.left,
        top: rect.top - storyRect.top,
        bottom: rect.bottom - storyRect.top,
        width: rect.width,
      };
    };
    return {
      storyWidth: storyRect.width,
      headline: toRelativeRect(headlineElement),
      deck: toRelativeRect(deckElement),
      image: toRelativeRect(imageElement),
    };
  }, articleId);
  assert.ok(rendered, `Expected rendered title-stacked media geometry for ${articleId}`);
  assert.ok(rendered.headline.left <= 1, `Expected headline to start at article left; found ${rendered.headline.left}`);
  assert.ok(rendered.headline.right >= rendered.storyWidth - 1, `Expected headline to span article width; found ${rendered.headline.right} of ${rendered.storyWidth}`);
  assert.ok(rendered.image.top >= rendered.headline.bottom - 0.75, `Expected image to clear headline; found image top ${rendered.image.top}, headline bottom ${rendered.headline.bottom}`);
  assert.ok(rendered.deck.right <= rendered.image.left + 1, `Expected deck to stay left of image; found deck right ${rendered.deck.right}, image left ${rendered.image.left}`);
  assert.ok(rendered.deck.top >= rendered.image.top - 0.75, `Expected deck top to align with image top`);
  assert.ok(rendered.deck.top < rendered.image.bottom, `Expected deck to float beside image`);
});

Then("the front article {string} should flow copy around the inset image", async function (articleId) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  const image = block.furniture.find((item) => item.kind === "image");
  assert.ok(image, `Expected ${articleId} to have solved image furniture`);
  const firstLineTops = block.columns.map((column) => column[0]?.y ?? null);
  assert.ok(firstLineTops.every((top) => top !== null), `Expected every ${articleId} column to contain copy`);
  const sideLineTops = firstLineTops.slice(0, image.columnStart);
  const imageColumnLineTops = firstLineTops.slice(image.columnStart, image.columnStart + image.columnSpan);
  assert.ok(sideLineTops.length > 0, `Expected ${articleId} to have text columns beside the inset image`);
  assert.ok(imageColumnLineTops.length > 0, `Expected ${articleId} to have image-cleared text columns`);
  assert.ok(
    sideLineTops.every((top) => top >= 0),
    `Expected side copy to remain inside the article frame; found ${firstLineTops.join(", ")}`,
  );
  assert.ok(
    imageColumnLineTops.every((top) => top >= image.y + image.height),
    `Expected right copy to clear image furniture; found ${firstLineTops.join(", ")}`,
  );
});

Then("the front article {string} should stack its image below title chrome", async function (articleId) {
  const block = await getFrontSolvedBlock(requirePage(this), articleId);
  assert.ok(block, `Expected solved front block for ${articleId}`);
  assert.equal(block.columnCount, 1);
  assert.equal(block.front?.composition?.mode, "stackedMedia");
  const image = block.furniture.find((item) => item.kind === "image");
  assert.ok(image, `Expected ${articleId} to have solved image furniture`);
  assert.equal(image.columnStart, 0);
  assert.equal(image.columnSpan, 1);
  const chromeBottom = Math.max(...(block.chromeBoxes ?? []).map((box) => box.y + box.height), 0);
  assert.ok(image.y >= chromeBottom, `Expected image y ${image.y} to clear chrome bottom ${chromeBottom}`);
  const firstLineY = block.columns[0]?.[0]?.y ?? null;
  assert.ok(firstLineY !== null, `Expected ${articleId} to render body copy below stacked image`);
  assert.ok(
    firstLineY >= image.y + image.height + block.front.chrome.jumpPaddingBottom,
    `Expected first line y ${firstLineY} to leave one rhythm row below image bottom ${image.y + image.height}`,
  );
  assert.ok(
    block.front.rowHeight >= firstLineY + block.columns[0][0].paintHeight + block.front.jumpReserveHeight,
    `Expected row height ${block.front.rowHeight} to contain stacked copy and jump label`,
  );

  const rendered = await requirePage(this).evaluate((targetArticleId) => {
    const story = document.querySelector(`.front-story[data-article-id="${targetArticleId}"]`);
    const imageElement = story?.querySelector(".lead-photo");
    const firstLine = story?.querySelector(".measured-line");
    const jump = story?.querySelector(".jump-line");
    const chromeBoxes = Array.from(story?.querySelectorAll(".front-chrome-box") ?? []);
    if (!story || !imageElement || !firstLine || !jump || chromeBoxes.length === 0) return null;
    const storyRect = story.getBoundingClientRect();
    const toRelativeRect = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: rect.top - storyRect.top,
        bottom: rect.bottom - storyRect.top,
        height: rect.height,
      };
    };
    return {
      chromeBottom: Math.max(...chromeBoxes.map((element) => toRelativeRect(element).bottom)),
      image: toRelativeRect(imageElement),
      firstLine: toRelativeRect(firstLine),
      jump: toRelativeRect(jump),
    };
  }, articleId);
  assert.ok(rendered, `Expected rendered stacked media geometry for ${articleId}`);
  assert.ok(rendered.image.top >= rendered.chromeBottom - 0.75, `Expected rendered image to clear chrome; found image top ${rendered.image.top}, chrome bottom ${rendered.chromeBottom}`);
  assert.ok(rendered.firstLine.top >= rendered.image.bottom + block.front.chrome.jumpPaddingBottom - 0.75, `Expected rendered body copy to leave one rhythm row below image`);
  assert.ok(rendered.jump.top >= rendered.firstLine.bottom - 0.75, `Expected rendered jump label to clear body copy`);
  assert.ok(rendered.jump.top >= rendered.image.bottom - 0.75, `Expected rendered jump label to clear stacked image`);
});

Then("the front lead trio should share one equal-height row", async function () {
  const articleIds = ["agent-procedure-patterns", "schools-reading-lab", "market-hall"];
  const solvedBlocks = await Promise.all(articleIds.map((articleId) => getFrontSolvedBlock(requirePage(this), articleId)));
  for (const [index, block] of solvedBlocks.entries()) {
    assert.ok(block, `Expected solved front block for ${articleIds[index]}`);
    assert.equal(block.hasMore, true, `Expected ${articleIds[index]} front teaser to continue`);
    assert.ok(block.front, `Expected front metrics for ${articleIds[index]}`);
  }

  const solvedRowHeights = solvedBlocks.map((block) => block.front.rowHeight);
  assert.ok(
    solvedRowHeights.every((height) => height === solvedRowHeights[0]),
    `Expected lead trio to share one solved row height; found ${solvedRowHeights.join(", ")}`,
  );
  const solvedBlockHeights = solvedBlocks.map((block) => block.height);
  assert.ok(
    solvedBlockHeights.every((height) => height === solvedBlockHeights[0]),
    `Expected lead trio to share one solved block height; found ${solvedBlockHeights.join(", ")}`,
  );

  const rendered = await requirePage(this).evaluate((targetArticleIds) => {
    return targetArticleIds.map((articleId) => {
      const story = document.querySelector(`.front-story[data-article-id="${articleId}"]`);
      if (!story) return null;
      const storyRect = story.getBoundingClientRect();
      const measure = story.querySelector(".story-measure");
      const measureRect = measure?.getBoundingClientRect();
      const lines = Array.from(story.querySelectorAll(".measured-line"));
      return {
        articleId,
        storyHeight: storyRect.height,
        measureBottom: measureRect ? measureRect.bottom - storyRect.top : 0,
        lineBottom: Math.max(...lines.map((line) => line.getBoundingClientRect().bottom - storyRect.top), 0),
      };
    });
  }, articleIds);
  assert.ok(rendered.every(Boolean), "Expected rendered front lead trio");

  const renderedHeights = rendered.map((story) => story.storyHeight);
  assert.ok(
    renderedHeights.every((height) => Math.abs(height - renderedHeights[0]) <= 1),
    `Expected rendered lead trio to share one row height; found ${renderedHeights.join(", ")}`,
  );

  const rhythm = await requirePage(this).evaluate(() => window.__PAPYRUS_LAYOUT__?.rhythm?.rowHeight ?? 19);
  for (const story of rendered) {
    const slack = story.measureBottom - story.lineBottom;
    assert.ok(
      slack >= -1 && slack <= rhythm * 2,
      `Expected ${story.articleId} copy to spend the shared row body area; found ${slack}px bottom slack`,
    );
  }

  const composedBlock = solvedBlocks.find((block) => block.id === "front-agent-procedure-patterns");
  assert.ok(composedBlock, "Expected composed center front block");
  const image = composedBlock.furniture.find((furniture) => furniture.kind === "image");
  assert.ok(image, "Expected center front block to have image furniture");
  const imageColumnIndexes = Array.from({ length: image.columnSpan }, (_, index) => image.columnStart + index);
  const imageBottom = image.y + image.height;
  const flowsBelowImage = imageColumnIndexes.some((columnIndex) => (
    (composedBlock.columns[columnIndex] ?? []).some((line) => line.y >= imageBottom - 0.75)
  ));
  assert.ok(
    flowsBelowImage,
    "Expected composed center body copy to resume in the image column after the image clears",
  );
});

Then(
  "the front headline for article {string} should be larger than articles {string} and {string}",
  async function (featureArticleId, firstRailArticleId, secondRailArticleId) {
    const featureBlock = await getFrontSolvedBlock(requirePage(this), featureArticleId);
    const firstRailBlock = await getFrontSolvedBlock(requirePage(this), firstRailArticleId);
    const secondRailBlock = await getFrontSolvedBlock(requirePage(this), secondRailArticleId);
    assert.ok(featureBlock, `Expected solved front block for ${featureArticleId}`);
    assert.ok(firstRailBlock, `Expected solved front block for ${firstRailArticleId}`);
    assert.ok(secondRailBlock, `Expected solved front block for ${secondRailArticleId}`);

    const featureSize = getSolvedHeadlineFontSize(featureBlock);
    const firstRailSize = getSolvedHeadlineFontSize(firstRailBlock);
    const secondRailSize = getSolvedHeadlineFontSize(secondRailBlock);
    assert.ok(featureSize > firstRailSize, `Expected ${featureArticleId} headline ${featureSize} > ${firstRailArticleId} ${firstRailSize}`);
    assert.ok(featureSize > secondRailSize, `Expected ${featureArticleId} headline ${featureSize} > ${secondRailArticleId} ${secondRailSize}`);
  },
);

Then("layout plan validation should accept headline scale {string}", function (headlineScale) {
  const { normalizeEditionLayoutPlan } = loadLayoutPlanModule();
  assert.doesNotThrow(() => normalizeEditionLayoutPlan(createHeadlineScalePlan(headlineScale), "test layoutPlan"));
});

Then("layout plan validation should reject headline scale {string}", function (headlineScale) {
  const { normalizeEditionLayoutPlan } = loadLayoutPlanModule();
  assert.throws(
    () => normalizeEditionLayoutPlan(createHeadlineScalePlan(headlineScale), "test layoutPlan"),
    /headlineScale|Invalid enum value/,
  );
});

Then("layout plan validation should accept editorial priority {string}", function (editorialPriority) {
  const { normalizeEditionLayoutPlan } = loadLayoutPlanModule();
  assert.doesNotThrow(() => normalizeEditionLayoutPlan(createEditorialPriorityPlan(editorialPriority), "test layoutPlan"));
});

Then("layout plan validation should reject editorial priority {string}", function (editorialPriority) {
  const { normalizeEditionLayoutPlan } = loadLayoutPlanModule();
  assert.throws(
    () => normalizeEditionLayoutPlan(createEditorialPriorityPlan(editorialPriority), "test layoutPlan"),
    /editorialPriority|Invalid enum value/,
  );
});

Then(
  "the {string} section should show a responsive pull quote",
  async function (articleId) {
    const solverSection = await getSolvedSection(requirePage(this), articleId);
    assert.ok(solverSection, `Expected solved section for ${articleId}`);
    assert.ok(solverSection.pullQuote, `Expected ${articleId} to have a solved pull quote`);
    assert.ok(
      String(solverSection.pullQuote.templateId).startsWith("pullquote-"),
      `Expected responsive pull quote template id; found ${solverSection.pullQuote.templateId}`,
    );
  },
);

Then("the {string} section should not show a pull quote", async function (articleId) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.equal(solverSection.pullQuote, null);
});

Then("responsive pull quotes should have no background", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    return Array.from(active?.querySelectorAll(".continuation-pullquote") ?? []).map((element) => {
      const style = window.getComputedStyle(element);
      return {
        article: element.closest(".solved-block--articleFrame")?.getAttribute("data-article-id") ?? "",
        backgroundColor: style.backgroundColor,
        backgroundImage: style.backgroundImage,
      };
    });
  });

  assert.ok(report.length > 0, "Expected at least one rendered pull quote");
  for (const quote of report) {
    assert.match(
      quote.backgroundColor,
      /rgba?\(0,\s*0,\s*0(?:,\s*0)?\)|transparent/,
      `Expected ${quote.article} pull quote background to be transparent; found ${quote.backgroundColor}`,
    );
    assert.equal(quote.backgroundImage, "none", `Expected ${quote.article} pull quote background image to be none`);
  }
});

Then("responsive pull quotes should fit their quote text without excess rows", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    const layout = window.__PAPYRUS_LAYOUT__;
    if (!layout || !active) return null;
    return Array.from(active.querySelectorAll(".continuation-pullquote")).map((element) => {
      const text = element.querySelector(".continuation-pullquote__text");
      const rect = element.getBoundingClientRect();
      const textRect = text?.getBoundingClientRect();
      return {
        article: element.closest(".solved-block--articleFrame")?.getAttribute("data-article-id") ?? "",
        height: rect.height,
        textHeight: textRect?.height ?? 0,
        excessHeight: rect.height - (textRect?.height ?? 0),
        rhythm: layout.rhythm.rowHeight,
      };
    });
  });

  assert.ok(report, "Expected pull quote geometry report");
  assert.ok(report.length > 0, "Expected at least one rendered pull quote");
  for (const quote of report) {
    assert.ok(quote.textHeight > 0, `Expected ${quote.article} pull quote text to render`);
    assert.ok(
      quote.excessHeight <= quote.rhythm * 2 + 4,
      `Expected ${quote.article} pull quote height to follow text; height=${quote.height}, textHeight=${quote.textHeight}, rhythm=${quote.rhythm}`,
    );
  }
});

Then("responsive pull quotes should leave one rhythm row before copy", async function () {
  const report = await requirePage(this).evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    const layout = window.__PAPYRUS_LAYOUT__;
    if (!layout || !active) return null;
    return Array.from(active.querySelectorAll(".continuation-pullquote")).map((quote) => {
      const quoteRect = quote.getBoundingClientRect();
      const section = quote.closest(".solved-block--articleFrame");
      const followingLines = Array.from(section?.querySelectorAll(".measured-line") ?? [])
        .map((line) => line.getBoundingClientRect())
        .filter((lineRect) => (
          lineRect.left < quoteRect.right - 0.75 &&
          lineRect.right > quoteRect.left + 0.75 &&
          lineRect.top >= quoteRect.bottom - 0.75
        ))
        .sort((first, second) => first.top - second.top);
      const forbiddenLines = followingLines.filter((lineRect) => (
        lineRect.top < quoteRect.bottom + layout.rhythm.rowHeight - 0.75
      ));
      return {
        article: section?.getAttribute("data-article-id") ?? "",
        gap: followingLines[0] ? followingLines[0].top - quoteRect.bottom : null,
        forbiddenLines: forbiddenLines.map((lineRect) => ({ top: lineRect.top, bottom: lineRect.bottom })),
        rhythm: layout.rhythm.rowHeight,
      };
    });
  });

  assert.ok(report, "Expected pull quote clearance report");
  assert.ok(report.length > 0, "Expected at least one rendered pull quote");
  for (const quote of report) {
    assert.deepEqual(quote.forbiddenLines, [], `Expected the row after ${quote.article} pull quote to stay blank`);
    if (quote.gap !== null) {
      assert.ok(
        quote.gap >= quote.rhythm - 0.75,
        `Expected one rhythm row after ${quote.article} pull quote; found ${quote.gap}px with rhythm ${quote.rhythm}px`,
      );
    }
  }
});

Then("the {string} section should exhaust the remaining article text", async function (articleId) {
  const solverSection = await getSolvedSection(requirePage(this), articleId);
  assert.ok(solverSection, `Expected solved section for ${articleId}`);
  assert.equal(solverSection.hasMore, false, `Expected ${articleId} continuation to exhaust remaining text`);
});

Then("the active continuation region should shrink to its solved blocks", async function () {
  const report = await getActiveContinuationRegionHeightReport(requirePage(this));
  assert.ok(report, "Expected active continuation region geometry");
  assert.ok(
    Math.abs(report.regionHeight - report.blockBottom) <= 0.75,
    `Expected region height ${report.regionHeight}px to match solved block bottom ${report.blockBottom}px`,
  );
});

Then("the active continuation region should preserve allocated fill height", async function () {
  const report = await getActiveContinuationRegionHeightReport(requirePage(this));
  assert.ok(report, "Expected active continuation region geometry");
  assert.ok(
    report.slackRows >= 8,
    `Expected default fill region to keep visible allocation slack; found ${report.slackRows} rows`,
  );
});

Then("the {string} section should hold exactly {int} default rows", async function (articleId, expectedRows) {
  const report = await getSolvedSectionRowReport(requirePage(this), articleId);
  assert.ok(report, `Expected solved section row report for ${articleId}`);
  assert.ok(
    Math.abs(report.height - expectedRows * report.rhythm) <= 0.75,
    `Expected ${articleId} section to hold ${expectedRows} rows; found ${report.rows} rows`,
  );
});

Then("the {string} section should grow beyond {int} default rows", async function (articleId, defaultRows) {
  const report = await getSolvedSectionRowReport(requirePage(this), articleId);
  assert.ok(report, `Expected solved section row report for ${articleId}`);
  assert.ok(
    report.rows > defaultRows + 0.5,
    `Expected ${articleId} section to grow beyond ${defaultRows} rows; found ${report.rows} rows`,
  );
});

Then("the {string} section should shrink below {int} default rows", async function (articleId, defaultRows) {
  const report = await getSolvedSectionRowReport(requirePage(this), articleId);
  assert.ok(report, `Expected solved section row report for ${articleId}`);
  assert.ok(
    report.rows < defaultRows - 0.5,
    `Expected ${articleId} section to shrink below ${defaultRows} rows; found ${report.rows} rows`,
  );
});

Then("no browser console errors should occur", async function () {
  assert.deepEqual(this.consoleErrors, []);
});

function requirePage(world) {
  assert.ok(world.page, "Expected an open Playwright page");
  return world.page;
}

function isMultipleOfRhythm(value, rhythm, tolerance = 0.75) {
  const remainder = Math.abs(value % rhythm);
  return remainder <= tolerance || Math.abs(remainder - rhythm) <= tolerance;
}

async function getSolvedSection(page, articleId) {
  return page.evaluate((targetArticleId) => {
    const pageNumber = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const layout = window.__PAPYRUS_LAYOUT__;
    const solvedPage = layout?.pages.find((candidate) => candidate.pageNumber === pageNumber);
    const block = solvedPage?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    if (!block) return null;
    const image = block.furniture.find((item) => item.kind === "image") ?? null;
    const pullQuote = block.furniture.find((item) => item.kind === "pullQuote") ?? null;
    return { ...block, image, pullQuote };
  }, articleId);
}

async function getSolvedSectionRowReport(page, articleId) {
  return page.evaluate((targetArticleId) => {
    const pageNumber = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const layout = window.__PAPYRUS_LAYOUT__;
    const solvedPage = layout?.pages.find((candidate) => candidate.pageNumber === pageNumber);
    const block = solvedPage?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId);
    if (!layout || !block) return null;
    return {
      height: block.height,
      rows: block.height / layout.rhythm.rowHeight,
      rhythm: layout.rhythm.rowHeight,
    };
  }, articleId);
}

async function getActiveContinuationRegionHeightReport(page) {
  return page.evaluate(() => {
    const pageNumber = window.__PAPYRUS_VISIBLE_PAGE__ ?? Number(document.querySelector(".site-shell")?.getAttribute("data-current-page") ?? 1);
    const layout = window.__PAPYRUS_LAYOUT__;
    const solvedPage = layout?.pages.find((candidate) => candidate.pageNumber === pageNumber);
    const region = solvedPage?.regions[0];
    if (!layout || !region) return null;
    const blockBottom = Math.max(...region.blocks.map((block) => block.y + block.height), 0);
    return {
      regionHeight: region.height,
      blockBottom,
      slackRows: (region.height - blockBottom) / layout.rhythm.rowHeight,
      rhythm: layout.rhythm.rowHeight,
    };
  });
}

async function getFrontSolvedBlock(page, articleId) {
  return page.evaluate((targetArticleId) => {
    const frontPage = window.__PAPYRUS_LAYOUT__?.pages.find((candidate) => candidate.pageNumber === 1);
    return frontPage?.regions
      .flatMap((region) => region.blocks)
      .find((candidate) => candidate.article?.slug === targetArticleId) ?? null;
  }, articleId);
}

function getSolvedHeadlineFontSize(block) {
  const composedHeadline = block.chromeBoxes?.find((box) => box.slot === "headline");
  return composedHeadline?.fontSize ?? block.front?.chrome?.headlineFontSize ?? 0;
}

function loadLayoutPlanModule() {
  registerTypeScriptRequire();
  return require(path.resolve(__dirname, "../../lib/layout-plan.ts"));
}

function loadEditionRoutesModule() {
  registerTypeScriptRequire();
  return require(path.resolve(__dirname, "../../lib/edition-routes.ts"));
}

function loadSemanticGraphModule() {
  registerTypeScriptRequire();
  return require(path.resolve(__dirname, "../../lib/semantic-graph.ts"));
}

function parseDatedTestPath(routePath) {
  const parts = routePath.split("/").filter(Boolean);
  assert.equal(parts.length >= 3, true, `Expected dated route path; got ${routePath}`);
  const [year, month, day, child, value] = parts;
  return {
    year,
    month,
    day,
    sectionKey: child === "section" ? value : undefined,
    articleSlug: child !== "section" ? child : undefined,
  };
}

function registerTypeScriptRequire() {
  if (require.extensions[".ts"]) return;
  require.extensions[".ts"] = (module, filename) => {
    const source = fs.readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        moduleResolution: ts.ModuleResolutionKind.Node10,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    });
    module._compile(output.outputText, filename);
  };
}

async function waitForNewsroomSection(page, sectionId) {
  await page.locator(`[data-news-desk-tab='${sectionId}'][aria-current='page']`).waitFor({ state: "visible", timeout: 10_000 });
  const sectionSelector = sectionId === "assignments"
    ? "[data-news-desk-assignments]"
    : `[data-news-desk-section='${sectionId}']`;
  await page.locator(sectionSelector).waitFor({ state: "visible", timeout: 10_000 });
}

function getNewsroomSectionId(label) {
  const normalized = String(label).trim().toLowerCase();
  if (normalized === "overview") return "overview";
  if (normalized === "users") return "administration";
  if (normalized === "administration") return "administration";
  if (normalized === "desks") return "topics";
  if (normalized === "topics") return "topics";
  if (normalized === "concepts") return "concepts";
  if (normalized === "references") return "references";
  if (normalized === "assignments") return "assignments";
  if (normalized === "sections") return "administration";
  if (normalized === "doctrine") return "administration";
  throw new Error(`Unknown newsroom section label: ${label}`);
}

function createHeadlineScalePlan(headlineScale) {
  return {
    pages: [
      {
        pageNumber: 1,
        presetId: "page.full",
        regions: [
          {
            id: "main",
            type: "fullPage",
            blocks: [
              {
                id: "headline-scale-check",
                type: "articleFrame",
                presetId: "article.standard",
                itemId: "example",
                startCursor: "beginning",
                typography: { headlineScale },
              },
            ],
          },
        ],
      },
    ],
  };
}

function createEditorialPriorityPlan(editorialPriority) {
  const plan = createHeadlineScalePlan("standard");
  plan.pages[0].regions[0].blocks[0].editorialPriority = editorialPriority;
  return plan;
}

async function getActivePageReport(page) {
  return page.evaluate(() => {
    const active = document.querySelector(".paper-page--active");
    if (!active) throw new Error("No active newspaper page");

    const toRect = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      };
    };
    const overlap = (a, b, gutter = 0) => (
      a.left < b.right + gutter &&
      a.right + gutter > b.left &&
      a.top < b.bottom + gutter &&
      a.bottom + gutter > b.top
    );
    const intersectionHeight = (a, b) => Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));

    const furniture = Array.from(active.querySelectorAll(".continuation-photo, .continuation-pullquote, .front-story .lead-photo")).map((element) => ({
      article: element.closest(".solved-block--articleFrame, .front-story")?.getAttribute("data-article-id") ?? "",
      className: String(element.className),
      rect: toRect(element),
    }));
    const furnitureOverlaps = [];
    for (let firstIndex = 0; firstIndex < furniture.length; firstIndex += 1) {
      for (let secondIndex = firstIndex + 1; secondIndex < furniture.length; secondIndex += 1) {
        const first = furniture[firstIndex];
        const second = furniture[secondIndex];
        if (first.article === second.article && overlap(first.rect, second.rect)) furnitureOverlaps.push({ first, second });
      }
    }

    const chromeOverlaps = [];
    for (const story of active.querySelectorAll(".front-story")) {
      const article = story.getAttribute("data-article-id") ?? "";
      const pairs = [
        [story.querySelector("h2"), story.querySelector(".story-deck"), "headline/deck"],
        [story.querySelector(".story-deck"), story.querySelector(".story-byline"), "deck/byline"],
        [story.querySelector(".story-byline"), story.querySelector(".story-measure"), "byline/body"],
        [story.querySelector(".story-measure"), story.querySelector(".jump-line"), "body/jump"],
      ];
      for (const [previous, next, label] of pairs) {
        if (!previous || !next) continue;
        const previousRect = toRect(previous);
        const nextRect = toRect(next);
        if (previousRect.bottom > nextRect.top + 0.75) chromeOverlaps.push({ article, label, previousRect, nextRect });
      }
    }
    for (const story of active.querySelectorAll(".front-story")) {
      const article = story.getAttribute("data-article-id") ?? "";
      const storyChrome = Array.from(story.querySelectorAll(".front-chrome-box")).map((element) => ({
        slot: element.getAttribute("data-chrome-slot") ?? "",
        rect: toRect(element),
      }));
      const storyFurniture = furniture.filter((item) => item.article === article);
      for (const line of story.querySelectorAll(".measured-line")) {
        const lineRect = toRect(line);
        for (const box of storyChrome) {
          if (overlap(lineRect, box.rect)) chromeOverlaps.push({ article, label: `line/${box.slot}`, previousRect: lineRect, nextRect: box.rect });
        }
        for (const item of storyFurniture) {
          if (overlap(lineRect, item.rect)) chromeOverlaps.push({ article, label: "line/front-furniture", previousRect: lineRect, nextRect: item.rect });
        }
      }
    }

    for (const section of active.querySelectorAll(".solved-block--articleFrame")) {
      const article = section.getAttribute("data-article-id") ?? "";
      const title = section.querySelector(".continued-title");
      const body = section.querySelector(".continuation-body");
      if (!title || !body) continue;
      const titleRect = toRect(title);
      const bodyRect = toRect(body);
      if (titleRect.bottom > bodyRect.top + 0.75) chromeOverlaps.push({ article, label: "continued-title/body", previousRect: titleRect, nextRect: bodyRect });
      const kicker = title.querySelector("p");
      const headline = title.querySelector("h2");
      if (kicker && headline) {
        const kickerRect = toRect(kicker);
        const headlineRect = toRect(headline);
        if (kickerRect.bottom > headlineRect.top + 0.75) chromeOverlaps.push({ article, label: "continued-kicker/headline", previousRect: kickerRect, nextRect: headlineRect });
      }
    }

    const clippedLines = [];
    const lineFurnitureOverlaps = [];
    for (const line of active.querySelectorAll(".measured-line")) {
      const container = line.closest(".story-measure, .continuation-column");
      if (!container) continue;
      const lineRect = toRect(line);
      const containerRect = toRect(container);
      if (lineRect.bottom > containerRect.bottom + 0.75 || line.scrollHeight > line.clientHeight + 1) {
        clippedLines.push({
          text: line.textContent,
          lineRect,
          containerRect,
        });
      }

      const article = line.closest(".solved-block--articleFrame, .front-story")?.getAttribute("data-article-id") ?? "";
      for (const item of furniture) {
        if (item.article === article && overlap(lineRect, item.rect)) {
          lineFurnitureOverlaps.push({
            article,
            line: line.textContent,
            furniture: item.className,
            lineRect,
            furnitureRect: item.rect,
          });
        }
      }
    }

    const deadColumns = [];
    for (const section of active.querySelectorAll(".solved-block--articleFrame")) {
      const article = section.getAttribute("data-article-id") ?? "";
      const sectionFurniture = furniture.filter((item) => item.article === article);
      const columns = Array.from(section.querySelectorAll(".continuation-column"));
      columns.forEach((column, columnIndex) => {
        const lineCount = column.querySelectorAll(".measured-line").length;
        if (lineCount > 0) return;

        const columnRect = toRect(column);
        const hasMeaningfulFurniture = sectionFurniture.some((item) => (
          overlap(columnRect, item.rect) &&
          intersectionHeight(columnRect, item.rect) >= Math.min(96, columnRect.height * 0.18)
        ));
        if (!hasMeaningfulFurniture) {
          deadColumns.push({
            article,
            columnIndex,
            columnRect,
          });
        }
      });
    }

    return {
      kind: active.getAttribute("data-page-kind") ?? (active.classList.contains("paper-page--front") ? "front" : null),
      clippedLines,
      chromeOverlaps,
      furnitureOverlaps,
      lineFurnitureOverlaps,
      deadColumns,
    };
  });
}

async function getActiveRhythmReport(page) {
  return page.evaluate(() => {
    const layout = window.__PAPYRUS_LAYOUT__;
    const active = document.querySelector(".paper-page--active");
    if (!layout) throw new Error("No solved newspaper layout");
    if (!active) throw new Error("No active newspaper page");

    const rhythm = layout.rhythm?.rowHeight ?? layout.pages?.[0]?.regions?.[0]?.blocks?.[0]?.columns?.[0]?.[0]?.lineHeight ?? 19;
    const tolerance = 0.75;
    const errors = [];
    const pageNumber = Number(active.id?.replace("page-", "") ?? 0);
    const solvedPage = layout.pages.find((candidate) => candidate.pageNumber === pageNumber);
    const pageRect = active.getBoundingClientRect();
    const pageContent = active.querySelector(".paper-page-content");

    const isOnRhythm = (value) => {
      const remainder = ((value % rhythm) + rhythm) % rhythm;
      return remainder <= tolerance || Math.abs(remainder - rhythm) <= tolerance;
    };
    const requireRhythm = (label, value) => {
      if (!Number.isFinite(value)) {
        errors.push({ label, value, reason: "not finite" });
        return;
      }
      if (!isOnRhythm(value)) errors.push({ label, value: Number(value.toFixed(3)), rhythm });
    };
    const requireClose = (label, value, expected) => {
      if (!Number.isFinite(value)) {
        errors.push({ label, value, expected, reason: "not finite" });
        return;
      }
      if (Math.abs(value - expected) > tolerance) {
        errors.push({ label, value: Number(value.toFixed(3)), expected: Number(expected.toFixed(3)), rhythm });
      }
    };
    const relativeRect = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: rect.top - pageRect.top,
        bottom: rect.bottom - pageRect.top,
        height: rect.height,
      };
    };

    if (solvedPage) {
      requireRhythm("solved page height", solvedPage.height);
      for (const region of solvedPage.regions) {
        requireRhythm(`solved region ${region.id} y`, region.y);
        requireRhythm(`solved region ${region.id} height`, region.height);
        for (const block of region.blocks) {
          requireRhythm(`solved block ${block.id} y`, block.y);
          requireRhythm(`solved block ${block.id} height`, block.height);
          if (block.front?.composition) {
            requireRhythm(`solved block ${block.id} body top`, block.front.composition.bodyTop);
            requireRhythm(`solved block ${block.id} body height`, block.front.composition.bodyHeight);
          }
          if (block.bodyHeight) requireRhythm(`solved block ${block.id} body height`, block.bodyHeight);
          for (const furniture of (block.furniture ?? [])) {
            requireRhythm(`solved furniture ${furniture.id} y`, furniture.y);
            requireRhythm(`solved furniture ${furniture.id} height`, furniture.height);
            requireRhythm(`solved furniture ${furniture.id} bottom`, furniture.y + furniture.height);
          }
        }
      }
    }

    if (pageContent) {
      const contentRect = relativeRect(pageContent);
      requireRhythm("rendered page height", contentRect.height);
    }
    const masthead = active.querySelector(".masthead");
    const mastheadMeta = active.querySelector(".masthead__meta");
    const frontGrid = active.querySelector(".front-grid");
    if (masthead) {
      const rect = relativeRect(masthead);
      requireRhythm("rendered masthead top", rect.top);
      requireRhythm("rendered masthead height", rect.height);
    }
    if (mastheadMeta) {
      const rect = relativeRect(mastheadMeta);
      requireRhythm("rendered masthead metadata top", rect.top);
      requireRhythm("rendered masthead metadata height", rect.height);
    }
    if (masthead && frontGrid) {
      const mastheadRect = relativeRect(masthead);
      const gridRect = relativeRect(frontGrid);
      requireRhythm("rendered front grid top", gridRect.top);
      requireClose("rendered masthead/front grid gap", gridRect.top - mastheadRect.bottom, rhythm);
    }
    for (const element of active.querySelectorAll(".front-story, .solved-region, .solved-block, .story-measure, .continuation-body")) {
      const rect = relativeRect(element);
      const label = element.getAttribute("data-block-id") ?? element.getAttribute("data-region-id") ?? String(element.className);
      requireRhythm(`rendered ${label} top`, rect.top);
      requireRhythm(`rendered ${label} height`, rect.height);
    }
    for (const line of active.querySelectorAll(".measured-line")) {
      const rect = relativeRect(line);
      requireRhythm(`rendered line ${line.textContent?.slice(0, 24) ?? ""} top`, rect.top);
    }
    for (const furniture of active.querySelectorAll(".continuation-photo, .continuation-pullquote, .front-story .lead-photo, .front-prelude-photo, .solved-ad")) {
      const rect = relativeRect(furniture);
      const label = furniture.closest("[data-block-id]")?.getAttribute("data-block-id") ?? String(furniture.className);
      requireRhythm(`rendered furniture ${label} top`, rect.top);
      requireRhythm(`rendered furniture ${label} height`, rect.height);
      requireRhythm(`rendered furniture ${label} bottom`, rect.bottom);
    }

    return { rhythm, errors };
  });
}

Then("the active page should swap raster image sources between light and dark theme", async function () {
  const page = requirePage(this);
  const report = await page.evaluate(async () => {
    const waitForPaint = async () => {
      await new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
      await new Promise((resolve) => window.setTimeout(resolve, 120));
    };
    const readFixtureSources = () => {
      const images = Array.from(
        document.querySelectorAll(".paper-page--active .lead-photo img, .paper-page--active .front-prelude-photo img, .paper-page--active .continuation-photo img"),
      );
      return images
        .map((image) => ({
          src: image.getAttribute("src") ?? "",
          srcSet: image.getAttribute("srcset") ?? "",
          alt: image.getAttribute("alt") ?? "",
        }))
        .filter((entry) => (
          entry.alt.includes("theme-specific")
          || entry.src.includes("theme-ink-study")
          || entry.srcSet.includes("theme-ink-study")
        ));
    };

    const applyTheme = (theme) => {
      const next = JSON.stringify({ theme, presentation: "newspaper", motion: "standard" });
      window.localStorage.setItem("papyrus:reader-settings", next);
      window.dispatchEvent(new CustomEvent("papyrus:settings-changed"));
    };

    applyTheme("light");
    await waitForPaint();
    const light = readFixtureSources();

    applyTheme("dark");
    await waitForPaint();
    const dark = readFixtureSources();

    applyTheme("system");

    return { light, dark };
  });

  assert.ok(report.light.length > 0, "Expected rendered raster fixture image sources in light mode");
  assert.ok(report.dark.length > 0, "Expected rendered raster fixture image sources in dark mode");
  if (JSON.stringify(report.light) === JSON.stringify(report.dark)) {
    throw new Error(`Expected light and dark raster image sources to differ; received ${JSON.stringify(report.dark)}`);
  }
  const darkSerialized = decodeURIComponent(JSON.stringify(report.dark));
  assert.match(
    darkSerialized,
    /theme-ink-study-dark\.png/,
    `Expected dark source to target theme-ink-study-dark.png; received ${JSON.stringify(report.dark)}`,
  );
});

function getPresentationFormatLabel(presentation) {
  if (presentation === "blog") return "Blog";
  if (presentation === "magazine") return "Magazine";
  return "Newspaper";
}
