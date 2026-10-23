import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FIXTURE_AUTOMATION_OVERVIEW } from "../lib/automation-fixture";
import {
  costText, durationText, inputTemplateText, parseRunInput, runNowMessage, statusMark, statusText, triggerText, whoText,
  type AutomationResult,
} from "../lib/automation-overview";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { AutomationView } = await import("../components/automation-view");
  const render = (result: AutomationResult | null, selectedId: string | null = null) =>
    renderToStaticMarkup(createElement(AutomationView, { result, selectedId, onSelect: () => {} }));

  // The list shows title, trigger, procedure, enabled and the last run status, all in words.
  const list = text(render(FIXTURE_AUTOMATION_OVERVIEW));
  for (const expected of [
    "Analyze new TTAB rulings", "Monitor ttab, delivering to example", "Procedure: example.ttab.ruling-analysis",
    "Enabled (the router starts nothing for a disabled automation)", "Last run: … Started, no result recorded yet, 2026-10-23 11:59 UTC",
    "Weekly digest", "Schedule (not yet supported)", "Disabled", "Last run: No runs",
    "Choose an automation to see its recent runs",
  ]) assert.ok(list.includes(expected), `list shows: ${expected}`);

  // Selecting one shows its detail and recent runs: started, duration, status, error, run id, story and cost.
  const html = render(FIXTURE_AUTOMATION_OVERVIEW, "example.ttab.ruling-analysis");
  const detail = text(html);
  for (const expected of [
    "Recent runs", "2026-10-23 11:30 UTC", "✓ Status: Completed", "3 min 10 s", "Item: 91000001-EXA_26", "Run run-1",
    "Story: Board affirms a refusal for likelihood of confusion", "Cost: unknown (not recorded",
    "✕ Status: Failed", "Error: the opinion could not be downloaded",
    "Status: Started, no result recorded yet", "Run record not linked yet", "Story: none recorded",
    "Linked: the router's trigger matches this record.", "proceeding = {sourceIdPrefix}",
    "2 items were not started because the Reference already existed",
    "about $0.05 per run, advisory", "the budget is advisory and only flagged",
  ]) assert.ok(detail.includes(expected), `detail shows: ${expected}`);

  // Cost is recorded and shown; a run over the advisory budget is flagged in words, not colour.
  for (const expected of [
    "Cost: $0.01 (estimated from the model usage reported by the run)",
    "Cost: unknown (not recorded for this run)",
    "Cost: $0.08 (estimated from the model usage reported by the run). Over the budget of $0.05 per run",
  ]) assert.ok(detail.includes(expected), `cost shows: ${expected}`);
  assert.match(html, /data-over-budget="true"/);

  // Run now by hand, a refused start and a skipped start are listed with who or why.
  for (const expected of [
    "Run now by ryan@example.test", "Status: Refused", "Reason: automation at its limit: 1 running, at most 1 at a time",
    "Status: Skipped", "Reason: automation disabled",
  ]) assert.ok(detail.includes(expected), `history shows: ${expected}`);

  // The procedure's other runs are listed apart, under their own heading.
  assert.ok(detail.includes("Started outside this automation"), "the outside runs have a heading");
  assert.ok(detail.includes("Started by: papyrus-cli") && detail.includes("Run run-9"), "an outside run says who started it");
  assert.ok(detail.indexOf("Started outside this automation") > detail.indexOf("Recent runs"), "outside runs come after the automation's own");
  assert.match(html, /data-automation-outside-run="run-9"/);

  // Run now: a button first, never a start on the first click.
  assert.match(html, /data-automation-run-now-start/);
  assert.ok(!html.includes("data-automation-run-now-confirm"), "no confirm step until the button is pressed");
  assert.match(html, /href="\/newsroom\/articles\/story-1"/, "the story links to its article");
  assert.match(html, /href="\/newsroom\/administration\/procedures"/, "the run links to the Procedures panel");

  // The confirm step says what will start, asks for the input of this run, and has a cancel.
  const { RunNowControl } = await import("../components/automation-run-now");
  const record = FIXTURE_AUTOMATION_OVERVIEW.automations[0];
  const confirming = renderToStaticMarkup(createElement(RunNowControl, { record, initialPhase: "confirming" }));
  const confirmText = text(confirming);
  for (const expected of [
    "Run example.ttab.ruling-analysis now?", "calls a model, which costs money", "limit of 1 at a time",
    "Input for this run (required)", "Confirm: start the run", "Cancel",
  ]) assert.ok(confirmText.includes(expected), `confirm step shows: ${expected}`);
  assert.match(confirming, /&quot;proceeding&quot;: &quot;&quot;/, "the input box starts from the record's input names");
  const demoConfirm = renderToStaticMarkup(createElement(RunNowControl, { record, initialPhase: "confirming", demo: true }));
  assert.match(demoConfirm, /data-automation-run-now-confirm-button[^>]*disabled|disabled[^>]*data-automation-run-now-confirm-button/, "the demo cannot start a run");
  const sent = renderToStaticMarkup(createElement(RunNowControl, { record, initialPhase: "done", initialMessage: runNowMessage({ state: "started", automationId: record.id, requestedBy: "x" }) }));
  assert.ok(text(sent).includes("Started. The run appears in the list below"));
  const unavailable = text(renderToStaticMarkup(createElement(RunNowControl, { record: FIXTURE_AUTOMATION_OVERVIEW.automations[1] })));
  assert.ok(unavailable.includes("Run now is not available: not yet supported"));
  const disabledRecord = { ...record, runNow: { available: false, reason: "disabled", needsInput: false, inputNames: [] } };
  assert.ok(text(renderToStaticMarkup(createElement(RunNowControl, { record: disabledRecord }))).includes("the automation is disabled. Enable it first"));

  // The input a person types is a JSON object or nothing.
  assert.deepEqual(parseRunInput(""), { ok: true, value: null });
  assert.deepEqual(parseRunInput('{"proceeding":"1"}'), { ok: true, value: { proceeding: "1" } });
  for (const bad of ["[1]", "3", "null", "{nope"]) assert.equal(parseRunInput(bad).ok, false, `refuses ${bad}`);
  assert.equal(inputTemplateText(["a", "b"]), '{\n  "a": "",\n  "b": ""\n}');

  // Every outcome of a Run now says so in words.
  assert.ok(runNowMessage({ state: "refused", reason: "this automation is disabled; enable it before running it." }).startsWith("Not started: this automation is disabled"));
  assert.ok(runNowMessage({ state: "unavailable" }).includes("Nothing was started"));
  assert.equal(runNowMessage({ error: "forbidden" }), "Run now is for editors and admins.");

  // A single automation opens its detail without a click; a stored schedule says nothing runs it.
  const single = { ...FIXTURE_AUTOMATION_OVERVIEW, automations: [FIXTURE_AUTOMATION_OVERVIEW.automations[1]] };
  const schedule = text(render(single));
  assert.ok(schedule.includes("Only monitor automations run today"));
  assert.ok(schedule.includes("No runs yet"));

  // Status is words and marks, never colour alone; no colour is encoded in the markup.
  assert.match(html, /data-run-status="failed"/);
  assert.ok(!/style=|color/.test(html), "no inline colour");

  // The word the product avoids does not appear in anything the page says.
  assert.ok(!/\bdesk\b/i.test(detail + list), "no avoided vocabulary");

  // Each state says so plainly.
  assert.ok(text(render({ error: "forbidden" })).includes("Automations are for editors and admins"));
  assert.ok(!render({ error: "forbidden" }).includes("Recent runs"), "a refused request shows no data");
  assert.ok(text(render({ state: "unavailable" })).includes("could not be read right now"));
  assert.ok(text(render({ ...FIXTURE_AUTOMATION_OVERVIEW, state: "empty", automations: [] })).includes("No automations yet"));
  assert.ok(text(render(null)).includes("Loading automations"));
  const notConnected = text(render({ ...FIXTURE_AUTOMATION_OVERVIEW, monitoring: "not_configured" }));
  assert.ok(notConnected.includes("Monitoring is not connected to this site's account"));

  // Wording helpers.
  assert.equal(statusText("startFailed"), "Could not start");
  assert.equal(statusText("refused"), "Refused");
  assert.equal(statusText("skipped"), "Skipped");
  assert.equal(statusMark("refused"), "✕");
  assert.equal(statusMark("skipped"), "–");
  assert.equal(costText({ costUsd: 1.5, costNote: "n", overBudget: false }), "Cost: $1.50 (n)");
  assert.equal(costText({ costUsd: 0.0004, costNote: "n", overBudget: false }), "Cost: $0.0004 (n)");
  assert.equal(whoText({ origin: "monitor", requestedBy: null, sourceId: "s1" }), "Item: s1");
  assert.equal(statusText(null), "No runs");
  assert.equal(statusMark("failed"), "✕");
  assert.equal(durationText(null), "duration not recorded");
  assert.equal(durationText(190), "3 min 10 s");
  assert.equal(triggerText({ kind: "manual", config: {} }), "Manual");

  console.log("automation page: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
