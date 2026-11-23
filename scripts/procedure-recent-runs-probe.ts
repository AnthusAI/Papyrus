// Renders a procedure's Recent Runs rows for the given ProcedureRun records and prints {runId: html} as JSON. Used by features_backend/agents/run-outcome-display.feature.
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ProcedureRunRecord } from "../lib/category-repository";

(globalThis as { React?: typeof React }).React = React;

async function main() {
  const { ProcedureRecentRunList } = await import("../components/procedure-recent-runs");
  const runs = JSON.parse(process.argv[2] ?? "[]") as ProcedureRunRecord[];
  const out: Record<string, string> = {};
  for (const run of runs) out[run.id] = renderToStaticMarkup(createElement(ProcedureRecentRunList, { runs: [run] }));
  process.stdout.write(JSON.stringify(out));
}

void main();
