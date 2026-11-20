// Renders the run outcome component for each outcome on its server string and prints {outcome: html} as JSON. Used by features_backend/agents/run-outcome-display.feature.
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as { React?: typeof React }).React = React;

async function main() {
  const { RunOutcome } = await import("../components/run-outcome");
  const given = JSON.parse(process.argv[2] ?? "{}") as Record<string, string>;
  const out: Record<string, string> = {};
  for (const [outcome, shown] of Object.entries(given)) out[outcome] = renderToStaticMarkup(createElement(RunOutcome, { outcome, shown }));
  process.stdout.write(JSON.stringify(out));
}

void main();
