import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FIXTURE_AUTOMATION_OVERVIEW } from "../lib/automation-fixture";
import { durationText, statusMark, statusText, triggerText, type AutomationResult } from "../lib/automation-overview";

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
    "Enabled (display only until the router honours it)", "Last run: … Started, no result recorded yet, 2026-10-23 11:59 UTC",
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
    "recorded only: the runner does not enforce these yet",
  ]) assert.ok(detail.includes(expected), `detail shows: ${expected}`);
  assert.match(html, /href="\/newsroom\/articles\/story-1"/, "the story links to its article");
  assert.match(html, /href="\/newsroom\/administration\/procedures"/, "the run links to the Procedures panel");

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
