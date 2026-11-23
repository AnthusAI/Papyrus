/**
 * Administration > Announcements, the "Review and timing" card (PPY-e2829f): the plain-words helpers, the edit-window rules the page checks before it saves (the
 * function checks them again, src/papyrus_content/announcements/edit_windows.py), and the review requests the page sends to the agent-policy function, which admits
 * only an admin on a person-only app client (src/papyrus_content/agent_policy/function.py; features_backend/agents/agent-policy-change.feature).
 */
import assert from "node:assert/strict";
import { Kind, parse, type FieldNode, type OperationDefinitionNode } from "graphql";
import { schema } from "../amplify/data/schema";
import { AGENT_POLICY_CHANGE, announcementReviewApi, createDemoReviewApi, reviewRefusalText } from "../lib/announcement-review-client";
import {
  DEFAULT_REVIEW_REASON, REVIEW_OPTIONS, currentReviewText, inheritedTimingText, resolveWindow, timingChanged, timingExplanation, timingFields, timingProblem, withXStoryTiming,
} from "../lib/announcement-review-timing";
import type { EditWindow } from "../lib/announcements-model";

// The three choices, in words, in the order hard, soft, none.
assert.deepEqual(REVIEW_OPTIONS.map((option) => [option.value, option.label]), [
  ["hard", "A person approves each post"], ["soft", "Posts on schedule unless someone steps in"], ["none", "Posts right away"],
]);

// The current review, with where it came from.
assert.equal(currentReviewText({ policyVersion: 3, approval: "hard", rung: "prepare", overrides: [], chosen: { approval: "soft", rung: "publish_soft", policy: "override: channel x, kind story_published (agent policy version 3)", reason: null } }),
  "Posts on schedule unless someone steps in. From the override: channel x, kind story_published (agent policy version 3).");
assert.equal(currentReviewText({ policyVersion: 0, approval: null, rung: "off", overrides: [], chosen: { approval: null, rung: "off", policy: "publication policy (agent policy version 0)", reason: "the announce agent is off, so no Delivery is prepared" } }),
  "No post is prepared: the announce agent is off, so no Delivery is prepared.");

// The window that applies to X story posts is the narrowest that fits, as edit_windows.resolve chooses.
const windows: EditWindow[] = [
  { windowMinutes: 1440, lockLeadMinutes: 60 },
  { channel: "email", windowMinutes: 10080, lockLeadMinutes: 60 },
  { kind: "story_published", windowMinutes: 30, lockLeadMinutes: 10 },
  { kind: "roundup", channel: "x", windowMinutes: 15, lockLeadMinutes: 5 },
];
assert.deepEqual(resolveWindow(windows, "story_published", "x"), { kind: "story_published", windowMinutes: 30, lockLeadMinutes: 10 });
assert.deepEqual(timingFields(windows), { windowMinutes: "30", lockLeadMinutes: "10" });
assert.match(inheritedTimingText(windows) ?? "", /every story published post/);
assert.deepEqual(timingFields([]), { windowMinutes: "", lockLeadMinutes: "" });
assert.equal(inheritedTimingText([]), null);

// Validation in edit_windows.py's words: whole minutes, zero or more, and the lock lead no longer than the window. Both blank is no window.
assert.equal(timingProblem({ windowMinutes: "60", lockLeadMinutes: "5" }), null);
assert.equal(timingProblem({ windowMinutes: "0", lockLeadMinutes: "0" }), null);
assert.equal(timingProblem({ windowMinutes: "60", lockLeadMinutes: "" }), null);
assert.equal(timingProblem({ windowMinutes: "", lockLeadMinutes: "" }), null);
assert.match(timingProblem({ windowMinutes: "1.5", lockLeadMinutes: "0" }) ?? "", /whole number/);
assert.match(timingProblem({ windowMinutes: "-1", lockLeadMinutes: "0" }) ?? "", /whole number/);
assert.match(timingProblem({ windowMinutes: "", lockLeadMinutes: "5" }) ?? "", /whole number/);
assert.match(timingProblem({ windowMinutes: "10", lockLeadMinutes: "15" }) ?? "", /more than the 10 minutes/);

// Saving sets the entry for X story posts and keeps every other entry as it was; blank takes that one entry away.
const set = withXStoryTiming(windows, { windowMinutes: "60", lockLeadMinutes: "5" });
assert.deepEqual(set.slice(0, 4), windows);
assert.deepEqual(set[4], { kind: "story_published", channel: "x", windowMinutes: 60, lockLeadMinutes: 5 });
const replaced = withXStoryTiming(set, { windowMinutes: "20", lockLeadMinutes: "" });
assert.equal(replaced.length, 5);
assert.deepEqual(replaced[4], { kind: "story_published", channel: "x", windowMinutes: 20, lockLeadMinutes: 0 });
assert.deepEqual(withXStoryTiming(set, { windowMinutes: "", lockLeadMinutes: "" }), windows);
assert.equal(timingChanged(windows, timingFields(windows)), true, "the inherited window is not yet X story posts' own");
assert.equal(timingChanged(set, { windowMinutes: "60", lockLeadMinutes: "5" }), false);
assert.equal(timingChanged(set, { windowMinutes: "60", lockLeadMinutes: "6" }), true);
assert.equal(timingChanged(undefined, { windowMinutes: "", lockLeadMinutes: "" }), false);

// One plain line for what soft and hard do at that time.
assert.equal(timingExplanation({ windowMinutes: "60", lockLeadMinutes: "5" }),
  "60 minutes after the draft is made, a soft post goes out unless someone has stopped it, and stops taking edits 5 minutes before; a post that needs a person's approval waits for one and shows as Overdue until then.");
assert.match(timingExplanation({ windowMinutes: "", lockLeadMinutes: "" }), /No time is set/);
assert.match(timingExplanation({ windowMinutes: "5", lockLeadMinutes: "9" }), /Fix the numbers/);

// The review requests: one field, agentPolicyChange, which the schema admits for admins only and hands to the agent-policy function; the page names no tenant.
const base = schema.transform().schema;
const declaration = base.split("\n").find((line) => line.trim().startsWith("agentPolicyChange(")) ?? "";
assert.match(declaration, /@function/);
assert.match(declaration, /groups: \["admin"\]\}/, declaration);
assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)|guest/.test(declaration), false, "agentPolicyChange is open to the admin group only");
const sent: Record<string, unknown>[] = [];
const answers: unknown[] = [];
const api = announcementReviewApi(async ({ query, variables }) => {
  const operation = parse(query).definitions.find((definition): definition is OperationDefinitionNode => definition.kind === Kind.OPERATION_DEFINITION);
  assert.equal(operation?.operation, "mutation");
  assert.equal((operation?.selectionSet.selections[0] as FieldNode).name.value, "agentPolicyChange");
  sent.push(JSON.parse(variables.input));
  return { data: { agentPolicyChange: JSON.stringify(answers.shift()) } };
});
assert.equal(AGENT_POLICY_CHANGE, "mutation AgentPolicyChange($input: AWSJSON) { agentPolicyChange(input: $input) }");

async function reviewRequests(): Promise<void> {
  answers.push({ ok: true, result: { policyVersion: 1, approval: "hard", rung: "prepare", overrides: [], chosen: { approval: "hard", rung: "prepare", policy: "publication policy (agent policy version 1)", reason: null } } });
  assert.equal((await api.show()).chosen?.approval, "hard");
  answers.push({ ok: true, result: { policyVersion: 2, approval: "soft", rung: "publish_soft", scope: { channel: "x", kind: "story_published" }, changed: true } });
  assert.equal((await api.set("soft", "  ")).rung, "publish_soft");
  answers.push({ ok: false, error: "human_required", message: "Only a person signed in to the console changes the agent policy. This credential is not one. Nothing was saved." });
  await assert.rejects(api.set("soft", "Launch"), /Only a person signed in to the console/);
  assert.deepEqual(sent, [
    { op: "announcements_review_show", channel: "x", kind: "story_published" },
    { op: "announcements_review_set", approval: "soft", channel: "x", kind: "story_published", reason: DEFAULT_REVIEW_REASON },
    { op: "announcements_review_set", approval: "soft", channel: "x", kind: "story_published", reason: "Launch" },
  ]);
  assert.ok(sent.every((request) => !("tenantId" in request) && !("actorKind" in request)), "the function takes the tenant and the caller from the session");
  const refused = announcementReviewApi(async () => ({ errors: [{ errorType: "Unauthorized", message: "Not Authorized to access agentPolicyChange on type Mutation" }] }));
  await assert.rejects(refused.show(), /Only an admin/);
  assert.equal(reviewRefusalText("human_required"), "Only a person signed in to the newsroom sets this. Nothing was saved.");

  // The demo holds the publish_auto floor, as the function does.
  const demo = createDemoReviewApi();
  assert.equal((await demo.show()).chosen?.approval, "hard");
  await assert.rejects(demo.set("none", ""), /publish_auto/);
  assert.equal((await demo.set("soft", "")).changed, true);
  assert.equal((await demo.show()).chosen?.approval, "soft");
}

void reviewRequests().then(() => console.log("announcement review and timing ok"), (error) => { console.error(error); process.exit(1); });
