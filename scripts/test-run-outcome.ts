import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const SHOWN: Record<string, string> = {
  acted: "✓ Did it", nothing: "– Nothing to do (no_new_filing)", asked: "? Asked (needs_review)", failed: "✗ Failed (timed_out)", unknown: "! Outcome unknown",
};

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { RunOutcome, outcomeWords } = await import("../components/run-outcome");

  // Every outcome shows its words and an icon; no text mark from the server string is shown.
  const html = Object.fromEntries(Object.entries(SHOWN).map(([outcome, shown]) => [outcome, renderToStaticMarkup(createElement(RunOutcome, { outcome, shown }))]));
  for (const [outcome, shown] of Object.entries(SHOWN)) {
    const text = html[outcome].replace(/<svg[\s\S]*?<\/svg>/g, "").replace(/<[^>]+>/g, "");
    assert.equal(text, outcomeWords(shown), `${outcome} shows its words`);
    assert.ok(!/[✓–?✗!]/.test(text.replace(/\(.*\)/, "")), `${outcome} shows no text mark`);
    assert.match(html[outcome], new RegExp(`<svg[^>]*data-outcome-mark="${outcome}"`), `${outcome} has an icon`);
  }

  // The five icons differ in shape, so they tell apart without colour.
  const shapes = Object.values(html).map((markup) => markup.match(/<svg[\s\S]*?<\/svg>/)![0].replace(/ data-outcome-mark="[^"]*"/, ""));
  assert.equal(new Set(shapes).size, 5, "five different icon shapes");

  // A run with no outcome yet shows its words alone.
  assert.equal(renderToStaticMarkup(createElement(RunOutcome, { outcome: null, shown: "Recorded before outcomes" })).includes("<svg"), false);
}

void main();
