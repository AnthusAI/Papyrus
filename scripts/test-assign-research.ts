import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { assignmentStateView, buildResearchAssignmentPlan, directionProblem } from "../lib/assign-research";
import { factCheckSentence, plainReason, researchPacketOf } from "../lib/research-packet";
import { failureReasonOf, isResearchAssignment } from "../lib/story-reporting-trail";

export const BROWSER_PLAN_INPUT = {
  lineageId: "story-1", storyTitle: "Courts and model output", sectionKey: "law-policy", stage: "idea",
  direction: "  Find the court rulings on model output  ", actorLabel: "An Editor", now: new Date("2026-11-03T12:00:00.000Z"),
};
const FIXTURE = join(__dirname, "..", "features_backend", "fixtures", "browser-assign-research.json");

test("the browser plan is the research assignment that the command makes", () => {
  const plan = buildResearchAssignmentPlan(BROWSER_PLAN_INPUT);
  assert.equal(plan.assignment.assignmentTypeKey, "research.multi");
  assert.equal(plan.assignment.itemLineageId, "story-1");
  assert.equal(plan.assignment.sectionKey, "law-policy");
  assert.equal(plan.assignment.title, "Courts and model output");
  assert.equal(plan.assignment.status, "open");
  assert.equal(plan.assignment.queueKey, "research:law-policy:exploratory");
  assert.equal(plan.assignment.queueStatusKey, "research:law-policy:exploratory#open");
  assert.equal(plan.assignment.newsroomFeedKey, "assignment#open");
  assert.equal(plan.assignment.id, "assignment-research-courts-and-model-output-20261103T120000000Z");
  assert.deepEqual([plan.event.eventType, plan.event.toStatus, plan.event.assignmentId], ["created", "open", plan.assignment.id]);
  assert.equal(plan.metadata.contextProfile, "reporter");
  assert.equal(plan.metadata.direction, "Find the court rulings on model output");
  assert.equal(plan.instructions, "Find the court rulings on model output");
});

test("the Assignment row carries no metadata, brief or instructions column: they are attachments", () => {
  const plan = buildResearchAssignmentPlan(BROWSER_PLAN_INPUT);
  for (const column of ["metadata", "brief", "instructions", "direction", "contextProfile"]) assert.equal(column in plan.assignment, false, column);
  assert.equal("metadata" in plan.event, false);
});

test("only a Story at the idea stage moves to the assignment stage", () => {
  assert.equal(buildResearchAssignmentPlan(BROWSER_PLAN_INPUT).movesStoryToAssignment, true);
  for (const stage of ["assignment", "research", "copywriting", "published", null]) assert.equal(buildResearchAssignmentPlan({ ...BROWSER_PLAN_INPUT, stage }).movesStoryToAssignment, false, String(stage));
});

test("a Story without a section is queued as unsectioned and an empty direction is refused", () => {
  const plan = buildResearchAssignmentPlan({ ...BROWSER_PLAN_INPUT, sectionKey: null });
  assert.equal(plan.assignment.queueKey, "research:unsectioned:exploratory");
  assert.equal(plan.assignment.sectionStatusKey, null);
  assert.ok(directionProblem("   "));
  assert.equal(directionProblem("Look into it"), null);
  assert.throws(() => buildResearchAssignmentPlan({ ...BROWSER_PLAN_INPUT, direction: "  " }));
});

test("what the browser writes is recorded for the Python test that builds the context pack from it", () => {
  const plan = buildResearchAssignmentPlan(BROWSER_PLAN_INPUT);
  const written = JSON.stringify({ assignment: plan.assignment, event: plan.event, metadata: plan.metadata, instructions: plan.instructions }, null, 2) + "\n";
  if (process.env.UPDATE_FIXTURES === "1") { mkdirSync(dirname(FIXTURE), { recursive: true }); writeFileSync(FIXTURE, written); }
  assert.equal(readFileSync(FIXTURE, "utf8"), written, "run UPDATE_FIXTURES=1 npx tsx --test scripts/test-assign-research.ts to rewrite the fixture");
});

test("assignment states are said in words", () => {
  assert.deepEqual(["open", "claimed", "completed", "failed"].map(status => assignmentStateView(status).state), ["waiting", "running", "finished", "failed"]);
  assert.equal(assignmentStateView("canceled").label, "canceled");
});

test("a failed assignment shows the reason of its latest failed event", () => {
  const events = [
    { id: "1", eventType: "claim", fromStatus: "open", toStatus: "claimed", actorLabel: "w", note: "started", createdAt: "2026-11-03T10:00:00Z" },
    { id: "2", eventType: "research.failed", fromStatus: "claimed", toStatus: "failed", actorLabel: "w", note: "no search provider answered", createdAt: "2026-11-03T10:05:00Z" },
  ];
  assert.equal(failureReasonOf({ status: "failed", events }), "no search provider answered");
  assert.equal(failureReasonOf({ status: "completed", events }), null);
  assert.equal(isResearchAssignment({ assignmentTypeKey: "research.multi" }), true);
  assert.equal(isResearchAssignment({ assignmentTypeKey: "research.candidate" }), false);
});

const packet = {
  summary: "Two providers agree.", recommended_angle: "Check the benchmark.",
  source_snapshots: [{ rank: 1, url: "https://a.example/x", title: "A", source_domain: "a.example" }, { rank: 2, url: "https://b.example/y", title: "", source_domain: "b.example" }],
  claims: [{ claim: "It shipped in October.", sources: [1, 2, 9] }, { claim: "", sources: [1] }],
  disagreements: [{ topic: "Score", positions: [{ position: "81 percent", sources: [1] }, { position: "76 percent", sources: [2] }] }, { topic: "", positions: [] }],
  open_questions: ["Who ran the benchmark?", 3],
};

test("a packet is read with claims linked to the sources they cite, and unknown source numbers are dropped", () => {
  const view = researchPacketOf(packet);
  assert.ok(view);
  assert.equal(view.summary, "Two providers agree.");
  assert.deepEqual(view.claims.map(claim => [claim.claim, claim.sources.map(source => source.url)]), [["It shipped in October.", ["https://a.example/x", "https://b.example/y"]]]);
  assert.equal(view.claims[0].sources[1].title, "https://b.example/y");
  assert.deepEqual(view.disagreements.map(item => [item.topic, item.positions.length]), [["Score", 2]]);
  assert.deepEqual(view.openQuestions, ["Who ran the benchmark?"]);
  assert.deepEqual(view.unverifiedClaims, []);
  assert.equal(view.factCheckSummary, null);
});

test("unverifiedClaims and factCheck are shown when present and the packet reads without them", () => {
  const view = researchPacketOf({ ...packet, unverifiedClaims: [
    { claim: "It won an award.", verdict: "needs_check", sources: [1], reasons: ["judge_partly_supported"] },
    { claim: "Rodney signed it.", verdict: "rejected", sources: [2], reasons: ["unmatched_terms: Rodney"] },
    { claim: "Old shape.", sources: [1], reasons: ["Only the maker says so."] }, { reasons: ["no claim"] }], factCheck: { summary: "One claim could not be verified." } });
  assert.ok(view);
  assert.deepEqual(view.unverifiedClaims.map(item => [item.claim, item.verdict, item.reasons, item.sources.length]), [
    ["It won an award.", "needs_check", ["The source only partly supports this"], 1],
    ["Rodney signed it.", "rejected", ["Not in the cited source: Rodney"], 1],
    ["Old shape.", null, ["Only the maker says so."], 1]]);
  assert.equal(view.factCheckSummary, "One claim could not be verified.");
});

test("the names a direction asked about and the run did not cover are listed, and a packet without them reads without", () => {
  const view = researchPacketOf({ ...packet, factCheck: { directionGaps: [
    { name: "Dana Woodruff", inSources: true, note: "The run has sources that mention Dana Woodruff but wrote nothing on Dana Woodruff." },
    { name: "Rowan Tesk" }, { note: "no name" }] } });
  assert.deepEqual(view?.directionGaps, [
    { name: "Dana Woodruff", note: "The run has sources that mention Dana Woodruff but wrote nothing on Dana Woodruff." },
    { name: "Rowan Tesk", note: "The run wrote nothing on Rowan Tesk." }]);
  assert.deepEqual(researchPacketOf(packet)?.directionGaps, []);
});

test("something that is not a packet reads as none", () => {
  assert.equal(researchPacketOf(null), null);
  assert.equal(researchPacketOf({ claims: [] }), null);
  assert.equal(researchPacketOf("text"), null);
});

test("the fact check sentence is made from the counts", () => {
  assert.equal(factCheckSentence({ verified: 12, needs_check: 8, rejected: 8, unchecked: 0, total: 28, singleSource: 23 }), "12 verified, 8 need a check, 8 rejected; 23 rest on one site");
  assert.equal(factCheckSentence({ verified: 3, unchecked: 2, singleSource: 0 }), "3 verified, 2 not checked");
  const view = researchPacketOf({ ...packet, factCheck: { counts: { verified: 1, needs_check: 1, rejected: 0, unchecked: 0, total: 2, singleSource: 1 } } });
  assert.equal(view?.factCheckSummary, "1 verified, 1 need a check; 1 rest on one site");
});

test("machine reasons are shown in plain words and unknown ones as they are", () => {
  assert.equal(plainReason("unmatched_terms: Rodney"), "Not in the cited source: Rodney");
  assert.equal(plainReason("judge_partly_supported"), "The source only partly supports this");
  assert.equal(plainReason("judge_failed: TimeoutError: the run ran short of time before this claim was checked"), "The run ran short of time before this claim was checked");
  assert.equal(plainReason("something new"), "something new");
});
