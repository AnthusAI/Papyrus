/**
 * The Automation page's pause, resume and wake now (PPY-e6f31e): the requests the console sends are the operation table's (`agents_pause`, `agents_resume`,
 * `agents_pauses`, `agents_wake`) through the doors `papyrus agents ...` uses, and the status reads in words with a mark, never colour alone.
 */
import assert from "node:assert/strict";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FIXTURE_AUTOMATION_OVERVIEW } from "../lib/automation-fixture";
import { AGENT_WAKE, agentPokeInApi, pauseText, resumeText } from "../lib/agent-poke-in";
import { AGENT_POLICY_CHANGE } from "../lib/announcement-review-client";
import type { AutomationResult } from "../lib/automation-overview";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

async function main() {
  (globalThis as { React?: typeof React }).React = React;

  // The console sends the operation table's names and input through the same doors as the command line.
  const sent: { query: string; input: Record<string, unknown> }[] = [];
  const answers: Record<string, unknown> = {
    agents_pauses: { policyVersion: 5, site: { paused: false }, agents: { announce: { paused: true, reason: "Checking the X drafts", pausedAt: "2026-11-23T15:00:00Z", pausedBy: "ada@example.test" } } },
    agents_pause: { scope: "agent", agent: "announce", paused: true, changed: true, policyVersion: { before: 4, after: 5 } },
    agents_resume: { scope: "agent", agent: "announce", paused: false, changed: true, policyVersion: { before: 5, after: 6 }, caughtUp: [{ agent: "announce", subject: "story-2", wakeKey: "k+resumed-v6", repeats: "k" }], notes: [] },
    agents_wake: { agent: "announce", subject: "story-1", wakeKey: "k+woken-r", repeats: "k", requestedBy: "edie@example.test", reason: "Again" },
  };
  const api = agentPokeInApi(async ({ query, variables }) => {
    const input = JSON.parse(variables.input) as Record<string, unknown>;
    sent.push({ query, input });
    const field = query === AGENT_WAKE ? "agentWake" : "agentPolicyChange";
    return { data: { [field]: JSON.stringify({ ok: true, result: answers[String(input.op)] }) } };
  });
  const pauses = await api.pauses();
  await api.pause("announce", " Checking the X drafts ");
  const resumed = await api.resume(null, "Incident closed");
  await api.wake("announce", "story-1", "Again");
  assert.deepEqual(sent.map((entry) => [entry.query, entry.input]), [
    [AGENT_POLICY_CHANGE, { op: "agents_pauses" }],
    [AGENT_POLICY_CHANGE, { op: "agents_pause", agent: "announce", reason: "Checking the X drafts" }],
    [AGENT_POLICY_CHANGE, { op: "agents_resume", reason: "Incident closed" }],
    [AGENT_WAKE, { op: "agents_wake", agent: "announce", subject: "story-1", reason: "Again" }],
  ]);
  assert.match(AGENT_WAKE, /\$input: AWSJSON!/, "agentWake's input is required, as the schema declares it");

  // A refusal reaches the page in the function's own words.
  const refusing = agentPokeInApi(async () => ({ data: { agentPolicyChange: JSON.stringify({ ok: false, error: "human_required", message: "Only a person signed in to the console changes the agent policy." }) } }));
  await assert.rejects(refusing.pause(null, "x"), /Only a person signed in to the console/);

  // Status in words with a mark.
  assert.deepEqual(pauseText({ paused: false }, "The site"), { mark: "▶", words: "The site is running." });
  assert.deepEqual(pauseText(pauses.agents.announce, "announce"), { mark: "⏸", words: "announce is paused by ada@example.test since 2026-11-23 15:00 UTC: Checking the X drafts" });
  assert.equal(resumeText(resumed, "The site"), "The site resumed. 1 stopped wake was sent again, one for each subject.");

  // The page: the site's pause in the header, and on an adopted agent its own pause and wake now.
  const { AutomationView } = await import("../components/automation-view");
  const announce = { ...FIXTURE_AUTOMATION_OVERVIEW, automations: (FIXTURE_AUTOMATION_OVERVIEW as { automations: object[] }).automations.map((record, index) =>
    index === 0 ? { ...record, id: "announce", title: "Announce", responsibility: "announce", trigger: { kind: "event", config: {} } } : record) } as AutomationResult;
  const pokeIn = {
    pauses: { state: "loaded" as const, site: pauses.site, agents: pauses.agents },
    onPause: api.pause, onResume: api.resume, onWake: api.wake,
  };
  const html = renderToStaticMarkup(createElement(AutomationView, { result: announce, selectedId: "announce", onSelect: () => {}, pokeIn }));
  const shown = text(html);
  for (const expected of [
    "The site is running.", "Pause The site",
    "Pause, resume, wake now", "announce is paused by ada@example.test since 2026-11-23 15:00 UTC: Checking the X drafts", "Resume announce", "Wake now",
  ]) assert.ok(shown.includes(expected), `the page shows: ${expected}`);
  assert.match(html, /data-agent-pause="announce" data-agent-pause-state="paused"/);
  assert.match(html, /data-agent-pause="site" data-agent-pause-state="running"/);

  // An editor, who may not read the pauses, is told so in words and still has wake now; without pokeIn the page shows none of it.
  const editor = text(renderToStaticMarkup(createElement(AutomationView, { result: announce, selectedId: "announce", onSelect: () => {},
    pokeIn: { ...pokeIn, pauses: { state: "forbidden" as const, message: "Pausing and resuming agents is for admins. Nothing was changed." } } })));
  assert.ok(editor.includes("Pausing and resuming agents is for admins.") && editor.includes("Wake now"));
  const without = renderToStaticMarkup(createElement(AutomationView, { result: announce, selectedId: "announce", onSelect: () => {} }));
  assert.doesNotMatch(without, /data-agent-pause|data-agent-wake/);

  console.log("agent poke-in: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
