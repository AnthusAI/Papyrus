import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DEMO_CYCLOTRON_STATUS } from "../lib/relevance-status";

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { PublicationCyclotronPanel } = await import("../components/publication-cyclotron-panel");
  const base = {
    contractVersion: "cyclotron-publication/v1" as const, accountId: "a", publicationId: "p", bindingRevision: "r1",
    outputs: [{ id: "o", question: "Relevant?", classes: ["yes", "no"], positiveLabel: "yes" }],
  };
  const render = (features: { frozenContext: boolean; replayExport: boolean; steering: boolean } | undefined, onSteer?: () => void) =>
    renderToStaticMarkup(createElement(PublicationCyclotronPanel, {
      mode: "remote", onSteer,
      status: { ...base, features, classifiers: { o: { ...DEMO_CYCLOTRON_STATUS, cyclotron: { ...DEMO_CYCLOTRON_STATUS.cyclotron, classifier: "o" } } } } as never,
      history: { ...base, features, history: [] } as never,
    }));
  const on = { frozenContext: true, replayExport: true, steering: true };
  const noop = () => undefined;

  // Steering true: today's live button.
  const live = render(on, noop);
  assert.match(live, /<button type="button">Test a rule change<\/button>/);
  assert.doesNotMatch(live, /Not available yet/);

  // Steering false or unknown: a disabled control with the reason, never a live one.
  for (const features of [{ ...on, steering: false }, undefined]) {
    const html = render(features, noop);
    assert.match(html, /<button type="button" disabled=""[^>]*>Test a rule change · Not available yet<\/button>/);
    assert.match(html, /cannot be tested on this service yet/);
    assert.doesNotMatch(html, /<button type="button">Test a rule change/);
  }

  // No handler from the host: nothing shown, as before.
  assert.doesNotMatch(render(on), /Test a rule change/);
  console.log("publication steering capability ok");
}
main();
