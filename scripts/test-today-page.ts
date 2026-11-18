import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FIXTURE_TODAY } from "../lib/today-fixture";
import { OTHER_WORDS, OUTCOME_WORDS, automationsHref, costText, countWords, dayTitle, dollars, reasonsText, type TodayResult } from "../lib/today-overview";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { TodayView } = await import("../components/today-view");
  const render = (result: TodayResult | null) => renderToStaticMarkup(createElement(TodayView, { result }));

  // A day with runs shows counts per responsibility and outcome, each as its words and its count.
  const html = render(FIXTURE_TODAY);
  const page = text(html);
  for (const expected of [
    "Today", "Monday 16 November 2026 · America/New_York", "15 runs · $0.43 (cost unknown for 1 run)",
    "Rate and curate", "Did it 6", "Nothing to do 1", "Asked 1", "Translate", "Did it 2", "Failed 1", "Outcome unknown 1", "Announce", "Nothing to do 3",
  ]) assert.ok(page.includes(expected), `page shows: ${expected}`);

  // A run that decided there was nothing to do shows its reason, without opening anything.
  assert.match(html, /data-today-reason="nothing"/);
  assert.ok(page.includes("Nothing to do: 2 not_rated, 1 under_channel_bar"), "the nothing-to-do reasons are on the line");
  assert.ok(page.includes("Failed: 1 timed_out") && page.includes("Asked: 1 needs_review"), "failed and asked reasons are on the line");

  // An agent that did not run says so and why.
  for (const expected of ["Did not run", "Weekly digest", "Disabled: the router starts nothing for a disabled automation", "Daily summary", "Nothing woke it today"])
    assert.ok(page.includes(expected), `did-not-run shows: ${expected}`);
  assert.match(html, /data-today-did-not-run="digest.weekly"[^>]*data-today-why="disabled"/);

  // One line per send: the lists, the items, the counts in words, the cost and where it stands, with a mark and its words.
  for (const expected of ["Sends", "weekly", "5 items", "no cost recorded", "Sent", "Sent 12", "Suppressed 1", "Skipped 2", "Delivered 11", "Bounced 1"])
    assert.ok(page.includes(expected), `a send shows: ${expected}`);
  assert.ok(!page.includes("Complained 0") && !page.includes("Queued 0"), "a count of zero is left out");
  assert.match(html, /data-today-send="announcement-weekly#email#site#g1"[^>]*data-today-send-state="sent"/);
  const status = /<p[^>]*data-today-send-status[^>]*>(.*?)<\/p>/.exec(html)?.[1] ?? "";
  assert.match(status, /<svg[^>]*aria-hidden="true"/, "a send's state has a mark");
  assert.ok(text(status).includes("Sent"), "and its words");
  assert.ok(!render({ ...FIXTURE_TODAY, sends: [] }).includes("data-today-sends"), "a day with no sends has no Sends section");

  // Cost is the sum of the runs; a run with no recorded cost is counted as unknown, not free.
  assert.ok(page.includes("3 runs · $0.00"), "the announce line costs nothing, and says so");
  assert.ok(page.includes("4 runs · $0.41 (cost unknown for 1 run)"), "the translate line says one run has no cost");
  assert.equal(costText({ costUsd: 0.41, costKnownRuns: 3, costUnknownRuns: 1 }), "$0.41 (cost unknown for 1 run)");
  assert.equal(costText({ costUsd: 0, costKnownRuns: 0, costUnknownRuns: 2 }), "cost unknown for 2 runs");
  assert.equal(costText({ costUsd: 0, costKnownRuns: 0, costUnknownRuns: 0 }), "no runs");
  assert.equal(dollars(0), "$0.00");
  assert.equal(dollars(0.0025), "$0.0025");

  // Each line opens the runs: the runs are listed under it, and it links to the Automation page for its automation.
  assert.match(html, /data-today-run="run-t2"[^>]*data-today-run-outcome="failed"/);
  assert.ok(page.includes("✗ Failed (timed_out)") && page.includes("Error: timed out after 840 s"), "a run lists its outcome words and error");
  assert.match(html, /href="\/newsroom\/administration\/automations\?automation=rate\.new-references"/, "a line links to its runs");
  assert.equal(automationsHref("a b"), "/newsroom/administration/automations?automation=a%20b");

  // Status is a mark and its words, never colour alone: every count and every run has an icon and the words, and no colour is in the markup.
  const counts = [...html.matchAll(/<li[^>]*data-today-count="([a-zA-Z]+)"[^>]*>(.*?)<\/li>/g)];
  assert.ok(counts.length === 7, "every count is listed");
  for (const [, key, inner] of counts) {
    assert.match(inner, /<svg[^>]*aria-hidden="true"/, `${key} has a mark`);
    assert.ok(text(inner).includes(countWords(key as never)), `${key} has its words`);
  }
  assert.ok(!/style=|color|border/.test(html.replace(/text-muted-foreground/g, "")), "no inline colour and no border classes");
  assert.equal(OUTCOME_WORDS.unknown, "Outcome unknown");
  assert.equal(OTHER_WORDS.beforeOutcomes, "Recorded before outcomes");

  // A run still going, and a run recorded before outcomes, are counted in words with a mark.
  const going = { ...FIXTURE_TODAY, rows: [{ ...FIXTURE_TODAY.rows[0], counts: { ...FIXTURE_TODAY.rows[0].counts, notFinished: 1, beforeOutcomes: 1 } }] };
  const goingText = text(render(going));
  assert.ok(goingText.includes("Not finished yet 1") && goingText.includes("Recorded before outcomes 1"));

  // A quiet day says so; the other states say so plainly; a refused request shows no data.
  assert.ok(text(render({ ...FIXTURE_TODAY, rows: [], didNotRun: [], totals: { ...FIXTURE_TODAY.totals, runs: 0, costKnownRuns: 0, costUnknownRuns: 0, costUsd: 0 } })).includes("Nothing ran in this day."));
  assert.ok(text(render(null)).includes("Loading what ran today"));
  assert.ok(text(render({ state: "unavailable" })).includes("could not be read right now"));
  assert.ok(text(render({ error: "forbidden" })).includes("Today is for editors and admins"));
  assert.ok(!render({ error: "forbidden" }).includes("What ran"), "a refused request shows no data");

  // Wording helpers.
  assert.equal(reasonsText({ under_channel_bar: 1, not_rated: 2 }), "2 not_rated, 1 under_channel_bar");
  assert.equal(dayTitle("2026-11-16"), "Monday 16 November 2026");
  assert.equal(dayTitle("not a day"), "not a day");

  // The word the product avoids does not appear in anything the page says.
  assert.ok(!/\bdesk\b/i.test(page), "no avoided vocabulary");

  console.log("today page: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
