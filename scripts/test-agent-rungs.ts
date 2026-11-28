/**
 * The Automation page's rung board: the console reads every agent's rung and sets one through the agent-policy function (`agents_rungs`, `agents_set_rung`),
 * with a person's ordinary admin sign-in, and shows the rung in words beside a Lucide icon. Backend behaviour: features_backend/agents/console-agent-rungs.feature.
 */
import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RungControl, type RungHandlers } from "../components/agent-rung-control";
import { agentRungsApi, createDemoRungsApi, rungChangeText, rungText, type RungBoard, type RungChange } from "../lib/agent-rungs";
import { AGENT_POLICY_CHANGE } from "../lib/announcement-review-client";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

async function main() {
  (globalThis as { React?: typeof React }).React = React;

  const board: RungBoard = { policyVersion: 3, agents: [{ id: "rate", responsibility: "rate", rung: "observe", ceiling: "propose", choices: ["off", "observe", "propose"], overrides: 0 }] };
  const change: RungChange = { id: "rate", responsibility: "rate", rung: "propose", ceiling: "propose", reason: "Let it suggest", changed: true, applied: true,
    before: { policyVersion: 3, entry: { rung: "observe" } }, after: { policyVersion: 4, entry: { rung: "propose" } },
    board: { policyVersion: 4, agents: [{ ...board.agents[0], rung: "propose" }] } };

  // The console sends the function's operation names through the agent-policy door.
  const sent: { query: string; input: Record<string, unknown> }[] = [];
  const answers: Record<string, unknown> = { agents_rungs: board, agents_set_rung: change };
  const api = agentRungsApi(async ({ query, variables }) => {
    const input = JSON.parse(variables.input) as Record<string, unknown>;
    sent.push({ query, input });
    return { data: { agentPolicyChange: JSON.stringify({ ok: true, result: answers[String(input.op)] }) } };
  });
  assert.deepEqual(await api.board(), board);
  assert.equal(rungChangeText(await api.setRung("rate", "propose", " Let it suggest ")), "rate changed from Watch only to Suggest (agent policy version 4). Its next run uses it.");
  assert.deepEqual(sent, [
    { query: AGENT_POLICY_CHANGE, input: { op: "agents_rungs" } },
    { query: AGENT_POLICY_CHANGE, input: { op: "agents_set_rung", agent: "rate", rung: "propose", reason: "Let it suggest" } },
  ]);

  // A refusal reads in the function's own words.
  const refusing = agentRungsApi(async () => ({ data: { agentPolicyChange: JSON.stringify({ ok: false, error: "human_required", message: "Only a person signed in to the console changes the agent policy." }) } }));
  await assert.rejects(refusing.setRung("rate", "propose", "x"), /Only a person signed in to the console/);
  const unauthorized = agentRungsApi(async () => ({ errors: [{ errorType: "Unauthorized", message: "Not Authorized" }] }));
  await assert.rejects(unauthorized.board(), /for admins/);

  // The control: the rung in words, the choices the definition allows, never above its ceiling.
  const handlers: RungHandlers = { rungs: { state: "loaded", agents: board.agents }, onSetRung: async () => change };
  const html = renderToStaticMarkup(createElement(RungControl, { responsibility: "rate", handlers }));
  assert.match(text(html), /rate: Watch only: runs and records what it would do; changes nothing\. The most it can be set to is Suggest\./);
  assert.match(html, /data-agent-rung-current="observe"/);
  assert.match(html, /class="lucide lucide-gauge/);
  const options = [...html.matchAll(/<option value="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(options, ["off", "observe", "propose"]);
  assert.match(html, /data-agent-rung-save/);

  // Not loaded, forbidden, or an agent the site did not register: words, and nothing to press.
  const loading = renderToStaticMarkup(createElement(RungControl, { responsibility: "rate", handlers: { ...handlers, rungs: null } }));
  assert.match(loading, /data-agent-rung-state="loading"/);
  const forbidden = renderToStaticMarkup(createElement(RungControl, { responsibility: "rate", handlers: { ...handlers, rungs: { state: "forbidden", message: "Setting an agent's rung is for admins. Nothing was changed." } } }));
  assert.match(text(forbidden), /for admins/);
  assert.doesNotMatch(forbidden, /data-agent-rung-save/);
  const unknown = renderToStaticMarkup(createElement(RungControl, { responsibility: "illustrate", handlers }));
  assert.match(text(unknown), /illustrate is not one of this site's registered agents/);

  assert.equal(rungText("propose"), "Suggest: writes suggestions for a person to accept or ignore");

  // The demo workspace answers the same way and refuses a rung above the ceiling.
  const demo = createDemoRungsApi();
  await assert.rejects(demo.setRung("rate", "draft", "More"), /Set it to propose or lower/);
  const demoChange = await demo.setRung("rate", "propose", "Try it");
  assert.equal(demoChange.after.entry?.rung, "propose");
  assert.equal((await demo.board()).agents.find((item) => item.id === "rate")?.rung, "propose");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
