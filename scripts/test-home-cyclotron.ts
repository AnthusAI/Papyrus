/** The newsroom home page's Cyclotron classifier panel: the words (unit) and the page at 375 and 1440 px (browser, synthetic data, no network). */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "playwright";
import {
  NOT_MEASURED, NO_RETRAINING_SENTENCE, describeClassifier, formatWhen, homeCyclotronStateFrom, newestPerOutput, parseHostedStatusRows,
  type HostedStatusRow,
} from "../lib/hosted-cyclotron-status";
import { DEMO_CYCLOTRON_STATUS } from "../lib/relevance-status";
import { setup } from "./test-notification-center-feed";

const row = (overrides: Partial<HostedStatusRow["status"]> = {}, extra: Partial<HostedStatusRow> = {}): HostedStatusRow => ({
  monitorId: "hn", publicationId: "anth-us", output: "anth-us-relevance", asOf: "2026-11-02T10:00:00.000Z", checkedAt: "2026-11-02T10:30:00.000Z",
  status: { ...DEMO_CYCLOTRON_STATUS, asOf: "2026-11-02T10:00:00.000Z", ...overrides }, ...extra,
});
const trained = (): HostedStatusRow => row({
  cyclotron: { ...DEMO_CYCLOTRON_STATUS.cyclotron, refits: 2, version: 4 },
  alignment: { ...DEMO_CYCLOTRON_STATUS.alignment, labels: 41, accuracy: 0.834 },
  lastChange: { kind: "refit", fromVersion: 3, toVersion: 4, at: "2026-10-30T14:05:00.000Z", summary: "refit on 41 reviews", labels: 41 },
  pending: { decisionsAwaitingReview: 3, staleSince: null },
});

const units: Record<string, () => void> = {
  words() {
    const never = describeClassifier(row(), { timeZone: "UTC" });
    assert.equal(never.retraining, NO_RETRAINING_SENTENCE, "no refits and no last change says so plainly");
    assert.equal(never.agreement, null);
    assert.ok(never.evaluation.endsWith(NOT_MEASURED), "a missing number says Not measured yet");
    assert.equal(never.retrained, false);
    assert.ok(never.counts[0].startsWith("No reviewed labels counted yet"));

    const done = describeClassifier(trained(), { timeZone: "UTC" });
    assert.match(done.retraining, /^Retrained 2 times\. Last change Oct 30, 2026: retrained on reviews, refit on 41 reviews\.$/);
    assert.equal(done.agreement, "83%");
    assert.equal(done.evaluation, "Agreement with reviewers 83%");
    assert.match(done.evaluationNote, /^Measured on reviews selected by the cyclotron: 41 reviews in the last 200\.$/);
    assert.ok(!/held-out accuracy/i.test(`${done.evaluation} ${done.evaluationNote}`), "the number is not called held-out accuracy");
    assert.deepEqual(done.counts, ["41 reviewed labels counted", "3 awaiting review"]);
    assert.equal(done.snapshot, "Snapshot from Nov 2, 2026, 10:00 AM");
    assert.match(done.freshness, /^Votes after the snapshot are not included yet\. Checked Nov 2, 2026, 10:30 AM\.$/);

    const changedOnly = describeClassifier(row({ lastChange: { kind: "definition", fromVersion: 1, toVersion: 2, at: null, summary: "question reworded", labels: null } }), { timeZone: "UTC" });
    assert.match(changedOnly.retraining, /^No retraining on reviews has happened yet\. Last change \(date not recorded\): questions or examples changed, question reworded\.$/, "a definition change is never called learning");
    const refitNoDate = describeClassifier(row({ cyclotron: { ...DEMO_CYCLOTRON_STATUS.cyclotron, refits: 1 } }), { timeZone: "UTC" });
    assert.equal(refitNoDate.retraining, "Retrained 1 time. The date of the last retraining was not recorded.");
    assert.equal(formatWhen("not a date"), "not a date");
    assert.equal(formatWhen(null), null);
  },
  states() {
    assert.deepEqual(homeCyclotronStateFrom({ rows: [] }), { state: "none" });
    assert.deepEqual(homeCyclotronStateFrom({ state: "unavailable" }), { state: "unavailable" });
    assert.deepEqual(homeCyclotronStateFrom({ error: "forbidden" }), { state: "unavailable" });
    assert.deepEqual(homeCyclotronStateFrom(null), { state: "unavailable" });
    assert.equal(parseHostedStatusRows({ rows: [{ status: { schema: "other" } }, "x", null] }).length, 0, "anything that is not a v1 snapshot is dropped");
    const older = row({}, { monitorId: "web", asOf: "2026-11-01T00:00:00.000Z" });
    const newer = row({}, { monitorId: "hn", asOf: "2026-11-02T00:00:00.000Z" });
    const second = row({}, { output: "anth-us-topic", monitorId: "hn" });
    const kept = newestPerOutput([older, newer, second]);
    assert.equal(kept.length, 2, "one block per output");
    assert.equal(kept.find((entry) => entry.output === "anth-us-relevance")?.monitorId, "hn", "the newest snapshot wins");
    const ready = homeCyclotronStateFrom({ rows: [older, newer] });
    assert.equal(ready.state === "ready" && ready.rows.length, 1);
  },
};

const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const shots = process.env.HOME_CYCLOTRON_SHOTS;
const shot = async (page: Page, name: string, width: number) => {
  if (!shots) return;
  fs.mkdirSync(shots, { recursive: true });
  await page.screenshot({ path: path.join(shots, `home-cyclotron-${name}-${width}.png`), fullPage: false });
};

/** The flat-fill, no-border, Lucide-only, no-dropdown rules for everything in the panel. */
async function assertDesignRules(page: Page, width: number) {
  const panel = page.locator("[data-home-cyclotron]");
  assert.equal(await panel.evaluate((node) => [node, ...node.querySelectorAll("*")].filter((el) => parseFloat(getComputedStyle(el).borderTopWidth) > 0 && getComputedStyle(el).borderTopStyle !== "none").length), 0, "no borders");
  for (const svg of await panel.locator("svg").all()) assert.ok(await svg.evaluate((node) => [...node.classList].some((name) => name.startsWith("lucide"))), "every icon is a Lucide icon");
  assert.equal(await panel.locator("select").count(), 0, "no dropdowns");
  assert.ok((await noHorizontalScroll(page)) <= 0, `no horizontal scroll at ${width}px`);
}

const browser: Record<string, () => Promise<void>> = {
  /** With a snapshot: top right of the header on a desktop, above the list on a phone; every fact is in words with an icon. */
  async snapshot() {
    for (const width of [375, 1440]) {
      const { browser: b, page, errors } = await setup("?only-batch=1&cyclotron=snapshot", width, width === 375 ? 900 : 900);
      try {
        const panel = page.locator("[data-home-cyclotron]");
        await panel.locator("[data-home-cyclotron-state='ready']").waitFor();
        const text = (await panel.textContent()) ?? "";
        for (const expected of ["Cyclotron classifier", "Classifier: relevant", "Retrained 2 times.", "Last change Oct 30, 2026: retrained on reviews, refit on 41 reviews.",
          "Agreement with reviewers 83%", "Measured on reviews selected by the cyclotron: 41 reviews in the last 200.", "41 reviewed labels counted", "3 awaiting review",
          "Snapshot from Nov 2, 2026", "Votes after the snapshot are not included yet."]) assert.ok(text.includes(expected), `the panel says: ${expected}`);
        assert.ok(!/held-out accuracy/i.test(text), "never called held-out accuracy");
        const box = (await panel.boundingBox())!;
        const title = (await page.locator("[data-notification-title]").boundingBox())!;
        const summary = (await page.locator("[data-notification-summary]").boundingBox())!;
        const filters = (await page.locator("[data-notification-filters]").boundingBox())!;
        if (width === 1440) {
          assert.ok(box.x > title.x + title.width, "on a desktop the panel is to the right of the title");
          assert.ok(box.y < title.y + title.height + 8 && box.y > title.y - 8, "and level with the top of the header");
          assert.ok(box.x + box.width > 1440 * 0.6, "in the top right");
        } else {
          assert.ok(box.y >= summary.y + summary.height - 1 && box.y + box.height <= filters.y + 1, "on a phone the panel sits under the title and above the list");
          assert.ok(box.x >= 0 && box.x + box.width <= 375, "inside the screen");
        }
        await assertDesignRules(page, width);
        await shot(page, "snapshot", width);
        await panel.locator("[data-home-cyclotron-details-toggle]").click();
        assert.ok(((await panel.textContent()) ?? "").includes("Relevant to this publication"), "the details are Cyclotron's own status card");
        await assertDesignRules(page, width);
        await shot(page, "snapshot-details", width);
        assert.deepEqual(errors, []);
      } finally { await b.close(); }
    }
  },
  /** Never trained: the plain sentence, no empty field, no number invented. */
  async never() {
    for (const width of [375, 1440]) {
      const { browser: b, page, errors } = await setup("?only-batch=1&cyclotron=never", width);
      try {
        const panel = page.locator("[data-home-cyclotron]");
        await panel.locator("[data-home-cyclotron-state='ready']").waitFor();
        const text = (await panel.textContent()) ?? "";
        for (const expected of ["No retraining has happened yet.", `Agreement with reviewers: ${NOT_MEASURED}`, "No reviewed labels counted yet", "12 awaiting review"]) assert.ok(text.includes(expected), `the panel says: ${expected}`);
        assert.ok(!/Retrained|Last change/.test(text), "no learning is implied");
        assert.ok(!/%/.test(await panel.locator("[data-home-cyclotron-evaluation]").innerText()), "no percentage appears for an unmeasured agreement");
        await assertDesignRules(page, width);
        await shot(page, "never-trained", width);
        assert.deepEqual(errors, []);
      } finally { await b.close(); }
    }
  },
  /** No snapshot, an unreadable one, and a slow one each say a plain sentence; none is a skeleton. */
  async sentences() {
    const cases: [string, string, string][] = [
      ["none", "none", "The Cyclotron has not reported on this site's classifier yet. A status appears here after the classifier's first completed decisions."],
      ["unavailable", "unavailable", "The classifier's status could not be read right now. Try again in a minute."],
      ["loading", "loading", "Reading the classifier’s status."],
    ];
    for (const [param, state, sentence] of cases) {
      for (const width of [375, 1440]) {
        const { browser: b, page, errors } = await setup(`?only-batch=1&cyclotron=${param}`, width);
        try {
          const panel = page.locator("[data-home-cyclotron]");
          await panel.locator(`[data-home-cyclotron-state='${state}']`).waitFor();
          assert.equal((await panel.locator(`[data-home-cyclotron-state='${state}']`).innerText()).trim(), sentence);
          assert.equal(await panel.locator(".animate-pulse, [data-skeleton]").count(), 0, "no skeleton");
          assert.equal(await panel.locator("[data-home-cyclotron-evaluation]").count(), 0, "no empty field");
          await assertDesignRules(page, width);
          await shot(page, param === "none" ? "no-snapshot" : param, width);
          // The feed is untouched by the panel in every state.
          await page.locator('[data-feed-card="rr-soft-2"]').waitFor();
          assert.deepEqual(errors, []);
        } finally { await b.close(); }
      }
    }
  },
  /** Without the loader (a site whose page has no Monitoring read) there is no panel at all. */
  async absent() {
    const { browser: b, page } = await setup("?only-batch=1", 1440);
    try {
      await page.locator('[data-feed-card="rr-soft-2"]').waitFor();
      assert.equal(await page.locator("[data-home-cyclotron]").count(), 0);
    } finally { await b.close(); }
  },
};

export async function runHomeCyclotronScenario(name: string) {
  if (units[name]) units[name]();
  else { assert.ok(browser[name], `Unknown home Cyclotron scenario: ${name}`); await browser[name](); }
  console.log(`Home Cyclotron scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : [...Object.keys(units), ...Object.keys(browser)]) await runHomeCyclotronScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
