/** The newsroom home page's Cyclotron classifier panel: the words (unit) and the page at 375 and 1440 px (browser, synthetic data, no network). */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "playwright";
import type { CyclotronStatus } from "cyclotron/cyclotron-status";
import {
  NOT_COMPARED, NOT_MEASURED, NO_RETRAINING_SENTENCE, REPORT_SCHEMA, describeClassifier, describeReport, formatWhen, homeCyclotronStateFrom, modelRows,
  newestPerOutput, parseHostedReport, parseHostedStatusRows,
  type HostedStatusRow,
} from "../lib/hosted-cyclotron-status";
import { DEMO_CYCLOTRON_STATUS } from "../lib/relevance-status";
import { setup } from "./test-notification-center-feed";

type StatusRow = HostedStatusRow & { status: CyclotronStatus };
const row = (overrides: Partial<CyclotronStatus> = {}, extra: Partial<Omit<HostedStatusRow, "status">> = {}): StatusRow => ({
  monitorId: "hn", publicationId: "anth-us", output: "anth-us-relevance", asOf: "2026-11-02T10:00:00.000Z", checkedAt: "2026-11-02T10:30:00.000Z",
  status: { ...DEMO_CYCLOTRON_STATUS, asOf: "2026-11-02T10:00:00.000Z", ...overrides }, ...extra,
});
const trained = (): StatusRow => row({
  cyclotron: { ...DEMO_CYCLOTRON_STATUS.cyclotron, refits: 2, version: 4 },
  alignment: { ...DEMO_CYCLOTRON_STATUS.alignment, labels: 41, accuracy: 0.834 },
  lastChange: { kind: "refit", fromVersion: 3, toVersion: 4, at: "2026-10-30T14:05:00.000Z", summary: "refit on 41 reviews", labels: 41 },
  pending: { decisionsAwaitingReview: 3, staleSince: null },
});


/** A report in the Cyclotron's real shape (src/decision_flywheel/classifier_report.py output_report), as the router stores it (plus `schema` and `generatedAt`). */
const rawReport = (overrides: Record<string, unknown> = {}) => ({
  schema: REPORT_SCHEMA, generatedAt: "2026-11-03T18:00:00.000000+00:00",
  classifier: { id: "anth-us-relevance", revision: 2, question: "Would a security engineer want to read this?", criteriaFingerprint: "cfp-1", rubric: "Include practical security news.", classes: ["include", "exclude"] },
  learning: { state: "not_active", reason: "standing runs do not train on votes yet; votes are stored and change no classifier", version: 4, refits: 2,
    lastChange: { kind: "refit", fromVersion: 3, toVersion: 4, at: "2026-10-30T14:05:00.000Z", summary: "refit on 41 reviews", labels: 41 }, asOf: "2026-11-03T17:00:00.000Z", unavailableReason: null },
  agreementWithEditors: { votes: 14, compared: 9, agreed: 7,
    byClassifierRevision: [{ classifierRevision: "1", votes: 3, compared: 0, agreed: 0 }, { classifierRevision: "2", votes: 11, compared: 9, agreed: 7 }],
    byDay: [{ day: "2026-11-03", votes: 8, compared: 6, agreed: 4 }, { day: "2026-11-01", votes: 3, compared: 0, agreed: 0 }, { day: "2026-11-02", votes: 3, compared: 3, agreed: 3 }] },
  heldOut: { accuracy: null, reason: "standing runs do not produce held-out evaluations yet" },
  counts: { labels: { include: 9, exclude: 5 }, reviewedDecisions: 12, primedExamples: 30, decisionsAwaitingReview: 4 },
  model: { features: null, weights: null, reason: "no machine-learning model has been fitted for this classifier" },
  ...overrides,
});
const beforeAnyDecision = () => rawReport({
  learning: { state: "not_active", reason: "standing runs do not train on votes yet; votes are stored and change no classifier", version: null, refits: null, lastChange: null, asOf: null, unavailableReason: "no decision has completed for this binding yet" },
  agreementWithEditors: { votes: 0, compared: 0, agreed: 0, byClassifierRevision: [], byDay: [] },
  counts: { labels: {}, reviewedDecisions: null, primedExamples: null, decisionsAwaitingReview: null },
});
const reportRow = (report: unknown, status: unknown = null) => ({ monitorId: "hn", publicationId: "anth-us", output: "anth-us-relevance", asOf: null, checkedAt: null, status, report, reportCheckedAt: "2026-11-03T18:05:00.000Z" });

const units: Record<string, () => void> = {
  words() {
    const never = describeClassifier(row(), { timeZone: "UTC" });
    assert.equal(never.retraining, NO_RETRAINING_SENTENCE, "no refits and no last change says so plainly");
    assert.equal(never.agreement, null);
    assert.ok(never.evaluation.endsWith(NOT_MEASURED), "a missing number says Not measured yet");
    assert.equal(never.retrained, false);
    assert.ok(never.counts[0].startsWith("No reviewed labels counted yet"));

    const done = describeClassifier(trained(), { timeZone: "UTC" });
    assert.match(done.retraining, /^Cycled 2 times\. Last change Oct 30, 2026: cycled on reviews, refit on 41 reviews\.$/);
    assert.equal(done.agreement, "83%");
    assert.equal(done.evaluation, "Agreement with reviewers 83%");
    assert.match(done.evaluationNote, /^Measured on reviews selected by the cyclotron: 41 reviews in the last 200\.$/);
    assert.ok(!/held-out accuracy/i.test(`${done.evaluation} ${done.evaluationNote}`), "the number is not called held-out accuracy");
    assert.deepEqual(done.counts, ["41 reviewed labels counted", "3 awaiting review"]);
    assert.equal(done.snapshot, "Snapshot from Nov 2, 2026, 10:00 AM");
    assert.match(done.freshness, /^Votes after the snapshot are not included yet\. Checked Nov 2, 2026, 10:30 AM\.$/);

    const changedOnly = describeClassifier(row({ lastChange: { kind: "definition", fromVersion: 1, toVersion: 2, at: null, summary: "question reworded", labels: null } }), { timeZone: "UTC" });
    assert.match(changedOnly.retraining, /^Not cycled on reviews yet\. Last change \(date not recorded\): questions or examples changed, question reworded\.$/, "a definition change is never called learning");
    const refitNoDate = describeClassifier(row({ cyclotron: { ...DEMO_CYCLOTRON_STATUS.cyclotron, refits: 1 } }), { timeZone: "UTC" });
    assert.equal(refitNoDate.retraining, "Cycled 1 time. The date of the last cycle was not recorded.");
    assert.equal(formatWhen("not a date"), "not a date");
    assert.equal(formatWhen(null), null);
  },
  report() {
    const report = parseHostedReport(rawReport())!;
    assert.ok(report, "the real shape parses");
    const facts = describeReport(report, { timeZone: "UTC" });
    assert.equal(facts.learning, "Learning: not active");
    assert.match(facts.learningReason ?? "", /standing runs do not train on votes yet/);
    assert.equal(facts.cycle, "Cycled 2 times. Last change Oct 30, 2026: cycled on reviews, refit on 41 reviews.");
    assert.equal(facts.agreement, "Agreement with reviewers: 7 of 9 compared");
    assert.match(facts.agreementNote, /^14 votes recorded, 5 not compared yet\. This is agreement, not accuracy/);
    assert.ok(!/accurac(y|ate)/i.test(facts.agreement), "agreement is never called accuracy");
    assert.deepEqual(facts.days.map((day) => [day.label, day.words]), [["Nov 3, 2026", "4 of 6 compared"], ["Nov 2, 2026", "3 of 3 compared"], ["Nov 1, 2026", "not compared yet (3 votes)"]], "newest day first");
    assert.equal(facts.days[2].share, null, "a day with nothing compared has no share");
    assert.deepEqual(facts.revisions, ["Classifier revision 2: 7 of 9 compared", "Classifier revision 1: not compared yet (3 votes)"]);
    assert.equal(facts.heldOut, "Held-out evaluation: standing runs do not produce held-out evaluations yet", "no accuracy: the report's own reason");
    assert.deepEqual(facts.counts, ["14 labels (include 9, exclude 5)", "12 reviewed decisions", "Started with 30 examples"]);
    assert.ok(!facts.counts.join(" ").includes("awaiting"), "decisionsAwaitingReview is not in the top counts");
    assert.match(facts.awaiting ?? "", /^4 decisions with no label filed in the engine yet\. On hosted runs this is only a count/);
    assert.equal(facts.question, "Would a security engineer want to read this?");
    assert.deepEqual(facts.supporting, { rows: [], reason: "no machine-learning model has been fitted for this classifier" }, "no supporting questions: the report's reason");
    assert.equal(describeReport(parseHostedReport(rawReport({ heldOut: { accuracy: 0.8125, reason: null } }))!).heldOut, "Held-out evaluation: 81%");
    assert.ok(!/%/.test(facts.agreement + facts.agreementNote), "no percentage for agreement");
  },
  reportZero() {
    const facts = describeReport(parseHostedReport(beforeAnyDecision())!, { timeZone: "UTC" });
    assert.equal(facts.agreement, `Agreement with reviewers: ${NOT_COMPARED}`, "0 compared reads Not compared yet");
    assert.ok(!/0%/.test(`${facts.agreement} ${facts.agreementNote}`), "never 0%");
    assert.match(facts.agreementNote, /^No votes recorded yet\./);
    assert.equal(facts.cycle, NO_RETRAINING_SENTENCE);
    assert.equal(facts.days.length, 0);
    assert.equal(facts.daysNote, "No days with votes yet.");
    assert.equal(facts.snapshot, "No snapshot yet: no decision has completed for this binding yet.");
    assert.deepEqual(facts.counts, ["0 labels"]);
    assert.equal(facts.awaiting, null);
    const votedNotCompared = describeReport(parseHostedReport(rawReport({ agreementWithEditors: { votes: 3, compared: 0, agreed: 0, byClassifierRevision: [], byDay: [{ day: "2026-11-03", votes: 3, compared: 0, agreed: 0 }] } }))!);
    assert.equal(votedNotCompared.agreement, `Agreement with reviewers: ${NOT_COMPARED}`);
    assert.match(votedNotCompared.agreementNote, /^3 votes recorded, none yet matched/);
    assert.equal(votedNotCompared.daysNote, "Only one day so far, so no change over time can be shown yet.", "a single day shows no trend");
  },
  reportModel() {
    const withModel = parseHostedReport(rawReport({ model: { features: ["mentions a vulnerability", "names a vendor"], weights: [1.25, -0.5], reason: null } }))!;
    assert.deepEqual(modelRows(withModel.model), [{ name: "mentions a vulnerability", weight: "1.25" }, { name: "names a vendor", weight: "-0.5" }]);
    assert.equal(describeReport(withModel).supporting.reason, null);
    assert.deepEqual(modelRows({ features: null, weights: { "a < b": 0.5 }, reason: null }), [{ name: "a < b", weight: "0.5" }], "names stay text");
    assert.deepEqual(modelRows({ features: null, weights: null, reason: "x" }), [], "missing weights give no rows");
  },
  reportParse() {
    assert.equal(parseHostedReport(rawReport({ schema: "cyclotron-classifier-report/v2" })), null, "an unknown schema is dropped");
    assert.equal(parseHostedReport({ ...rawReport(), schema: undefined }), null);
    assert.equal(parseHostedReport(rawReport({ agreementWithEditors: { votes: 5, compared: 2, agreed: 3, byClassifierRevision: [], byDay: [] } })), null, "agreed more than compared is not a report");
    assert.equal(parseHostedReport(rawReport({ agreementWithEditors: { votes: "x" } })), null, "a section out of shape drops the whole report");
    assert.equal(parseHostedReport(rawReport({ counts: null })), null);
    assert.equal(parseHostedReport("report"), null);
    const rows = parseHostedStatusRows({ rows: [
      reportRow(rawReport(), row().status),            // both
      { ...reportRow(rawReport()), output: "report-only" },     // report only
      { ...row(), report: undefined },                   // status only, as an older router wrote it
      reportRow(rawReport({ schema: "old" })),         // an unknown report and no status: dropped
      { ...row(), report: { schema: "old" } },         // an unknown report beside a status: the status is kept alone
    ] });
    assert.deepEqual(rows.map((entry) => [entry.output, entry.status !== null, entry.report !== null]), [
      ["anth-us-relevance", true, true], ["report-only", false, true], ["anth-us-relevance", true, false], ["anth-us-relevance", true, false]]);
    assert.equal(rows[1].status, null);
    const ready = homeCyclotronStateFrom({ rows: [reportRow(rawReport())] });
    assert.equal(ready.state === "ready" && ready.rows.length, 1, "a report-only row is served");
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
  await page.screenshot({ path: path.join(shots, `${name.startsWith("report") ? name : `home-cyclotron-${name}`}-${width}.png`), fullPage: false });
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
        for (const expected of ["Cyclotron classifier", "Classifier: relevant", "Cycled 2 times.", "Last change Oct 30, 2026: cycled on reviews, refit on 41 reviews.",
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
  /** With a report: learning, the cycle, agreement by day and the decision elements; the status-only panel above still works without one. */
  async reportPanel() {
    for (const width of [375, 1440]) {
      const { browser: b, page, errors } = await setup("?only-batch=1&cyclotron=report", width, 900);
      try {
        const panel = page.locator("[data-home-cyclotron]");
        await panel.locator("[data-home-cyclotron-state='ready']").waitFor();
        const text = (await panel.textContent()) ?? "";
        for (const expected of ["Learning: not active", "standing runs do not train on votes yet", "Cycled 2 times.", "Version 4", "Agreement with reviewers: 7 of 9 compared", "14 votes recorded, 5 not compared yet",
          "This is agreement, not accuracy", "Over time", "Nov 3, 2026", "4 of 6 compared", "Nov 1, 2026", "not compared yet (3 votes)", "Classifier revision 2: 7 of 9 compared",
          "Held-out evaluation: standing runs do not produce held-out evaluations yet", "14 labels (include 9, exclude 5)", "12 reviewed decisions", "Started with 30 examples", "Snapshot from Nov 2, 2026"]) assert.ok(text.includes(expected), `the panel says: ${expected}`);
        assert.ok(!text.includes("Question"), "the decision elements are folded away");
        assert.ok(!/awaiting/.test(text), "decisions awaiting review is not in the top section");
        assert.equal(await panel.locator("[data-home-cyclotron-day]").count(), 3);
        await assertDesignRules(page, width);
        await shot(page, "report-collapsed", width);
        await panel.locator("[data-home-cyclotron-details-toggle]").click();
        const open = (await panel.textContent()) ?? "";
        for (const expected of ["Would a security engineer at a mid-sized company want to read this?", "include, exclude", "Include practical security news. Exclude marketing.", "None yet. no machine-learning model has been fitted",
          "4 decisions with no label filed in the engine yet", "Relevant to this publication"]) assert.ok(open.includes(expected), `the details say: ${expected}`);
        await assertDesignRules(page, width);
        await shot(page, "report-expanded", width);
        assert.deepEqual(errors, []);
      } finally { await b.close(); }
    }
  },
  /** A very long rubric is folded and wraps when opened; a report with a model lists its supporting questions and weights and its held-out percentage. */
  async reportLongPanel() {
    for (const width of [375, 1440]) {
      const { browser: b, page, errors } = await setup("?only-batch=1&cyclotron=report-long", width, 900);
      try {
        const panel = page.locator("[data-home-cyclotron]");
        await panel.locator("[data-home-cyclotron-state='ready']").waitFor();
        await panel.locator("[data-home-cyclotron-details-toggle]").click();
        const fold = panel.locator("[data-home-cyclotron-rubric-fold]");
        assert.equal(await fold.count(), 1, "a long rubric is collapsed");
        assert.equal(await fold.evaluate((node) => (node as HTMLDetailsElement).open), false);
        await fold.locator("summary").click();
        assert.ok(((await fold.textContent()) ?? "").includes("Include a reference when it reports a new attack technique"));
        await assertDesignRules(page, width);
        await shot(page, "report-long-rubric", width);
        assert.deepEqual(errors, []);
      } finally { await b.close(); }
    }
    const { browser: b, page, errors } = await setup("?only-batch=1&cyclotron=report-model", 375, 900);
    try {
      const panel = page.locator("[data-home-cyclotron]");
      await panel.locator("[data-home-cyclotron-state='ready']").waitFor();
      assert.ok(((await panel.textContent()) ?? "").includes("Held-out evaluation: 81%"));
      await panel.locator("[data-home-cyclotron-details-toggle]").click();
      const supporting = (await panel.locator("[data-home-cyclotron-supporting]").textContent()) ?? "";
      assert.ok(supporting.includes("mentions a vulnerability") && supporting.includes("weight 1.25") && supporting.includes("weight -0.5"));
      await assertDesignRules(page, 375);
      assert.deepEqual(errors, []);
    } finally { await b.close(); }
  },
  /** Before the first decision the report still shows: 0 compared reads Not compared yet, never 0%, and there is no status snapshot. */
  async reportZeroPanel() {
    for (const width of [375, 1440]) {
      const { browser: b, page, errors } = await setup("?only-batch=1&cyclotron=report-zero", width, 900);
      try {
        const panel = page.locator("[data-home-cyclotron]");
        await panel.locator("[data-home-cyclotron-state='ready']").waitFor();
        const text = (await panel.textContent()) ?? "";
        for (const expected of ["Agreement with reviewers: Not compared yet", "No votes recorded yet.", "Not cycled yet.", "No days with votes yet.", "No snapshot yet: no decision has completed for this binding yet."]) assert.ok(text.includes(expected), `the panel says: ${expected}`);
        assert.ok(!/\b0%/.test(text), "never 0%");
        assert.equal(await panel.locator("[data-home-cyclotron-day]").count(), 0);
        await assertDesignRules(page, width);
        await shot(page, "report-zero", width);
        await panel.locator("[data-home-cyclotron-details-toggle]").click();
        assert.ok(((await panel.textContent()) ?? "").includes("no status snapshot"));
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
        for (const expected of ["Not cycled yet.", `Agreement with reviewers: ${NOT_MEASURED}`, "No reviewed labels counted yet", "12 awaiting review"]) assert.ok(text.includes(expected), `the panel says: ${expected}`);
        assert.ok(!/Cycled|Last change/.test(text), "no learning is implied");
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
