import assert from "node:assert/strict";
import test from "node:test";
import {
  checklistProgressLabel,
  checklistProgressText,
  formatStepTime,
  projectStoryStepIssues,
  stepActorText,
  storyChecklistSummary,
  summarizeStoryChecklist,
  type StoryStepRecord,
} from "../lib/story-checklist";
import { projectContentItemBoard } from "../lib/newsroom-board";
import { createLocalPreviewContentItemVersions, createLocalPreviewStoryChecklist } from "../lib/local-preview-seed";

const summary = { templateVersion: 2, total: 9, open: 3, done: 3, skipped: 2, not_applicable: 1, requiredOpen: ["draft"] };

function step(key: string, order: number, state: StoryStepRecord["state"], extra: Partial<StoryStepRecord> = {}): StoryStepRecord {
  return { id: `step-s1-${key}`, storyLineageId: "s1", stepKey: key, stepOrder: order, templateVersion: 2, state, ...extra };
}

test("the card line is done and not-applicable steps over all steps, then the skipped count", () => {
  assert.equal(checklistProgressText(summary), "4/9 · 2 skipped");
  assert.equal(checklistProgressText({ ...summary, skipped: 0, not_applicable: 0 }), "3/9");
  assert.match(checklistProgressLabel(summary), /^Checklist: 4\/9 · 2 skipped \(3 done, 1 not applicable, 2 skipped, 3 open\)$/);
});

test("the summary is read from a version's metadata, as an object or as the JSON text the backend stores", () => {
  assert.deepEqual(storyChecklistSummary({ checklist: summary }), summary);
  assert.deepEqual(storyChecklistSummary(JSON.stringify({ frontMatterYaml: "x", checklist: summary })), summary);
  assert.equal(storyChecklistSummary(null), null);
  assert.equal(storyChecklistSummary("not json"), null);
  assert.equal(storyChecklistSummary({ checklist: { total: 0 } }), null, "a Story with no steps has no summary");
  assert.deepEqual(storyChecklistSummary({ checklist: { total: 2, done: 1, open: 1 } })?.requiredOpen, [], "missing fields read as zero or empty");
});

test("summarizing steps counts each state and lists the required steps still open", () => {
  const steps = [step("choose", 0, "done"), step("outline", 3, "skipped"), step("draft", 4, "open"), step("publish", 10, "open")];
  assert.deepEqual(summarizeStoryChecklist(steps, ["choose", "outline", "draft"], 2), {
    templateVersion: 2, total: 4, open: 2, done: 1, skipped: 1, not_applicable: 0, requiredOpen: ["draft"],
  });
});

test("steps are Kanbus sub-tasks of the Story card, in template order, with their state as status", () => {
  const issues = projectStoryStepIssues("contentItem:s1", [step("draft", 4, "open", { title: "Write the draft" }), step("choose", 0, "done", { actorLabel: "AI", actorKind: "agent" })]);
  assert.deepEqual(issues.map(issue => [issue.type, issue.parent, issue.status, issue.title]), [
    ["sub-task", "contentItem:s1", "done", "choose"],
    ["sub-task", "contentItem:s1", "open", "Write the draft"],
  ]);
  assert.equal(issues[0].assignee, "AI");
});

test("who and when read in plain words", () => {
  assert.equal(stepActorText({ actorKind: "agent", actorLabel: "AI" }), "AI (agent)");
  assert.equal(stepActorText({ actorKind: "person", actorLabel: "Ryan" }), "Ryan");
  assert.equal(stepActorText({ actorKind: "system", actorLabel: "evidence" }), "evidence");
  assert.equal(stepActorText({}), "");
  assert.equal(formatStepTime("2026-11-07T10:00:00.000Z"), "7 Nov 2026, 10:00 UTC");
  assert.equal(formatStepTime(null), "");
  assert.equal(formatStepTime("nonsense"), "");
});

test("a board card carries the checklist counts of its Story, and a Story without them has none", () => {
  const [withChecklist, without] = projectContentItemBoard({
    contentItemVersions: [
      { id: "s1-v1", lineageId: "s1", versionNumber: 1, stage: "copywriting", type: "article", status: "draft", slug: "a", title: "A", metadata: JSON.stringify({ checklist: summary }) },
      { id: "s2-v1", lineageId: "s2", versionNumber: 1, stage: "copywriting", type: "article", status: "draft", slug: "b", title: "B", metadata: "{}" },
    ],
  });
  assert.deepEqual(withChecklist.checklist, summary);
  assert.equal("checklist" in without, false);
});

test("every preview Story carries a checklist summary that matches its panel's steps", () => {
  for (const version of createLocalPreviewContentItemVersions()) {
    const steps = createLocalPreviewStoryChecklist(version.lineageId);
    const carried = storyChecklistSummary(version.metadata);
    assert.ok(carried, `${version.lineageId} has a summary`);
    assert.equal(steps.length, carried.total);
    assert.equal(steps.filter(item => item.state === "done").length, carried.done);
    assert.equal(steps.filter(item => item.state === "skipped").length, carried.skipped);
  }
});

test("a reason or findings note is stored with every skipped, not-applicable and review step that is done", () => {
  for (const version of createLocalPreviewContentItemVersions()) {
    for (const item of createLocalPreviewStoryChecklist(version.lineageId)) {
      if (item.state === "skipped" || item.state === "not_applicable") assert.ok(item.reason, `${item.id} has a reason`);
      if (item.state === "done" && item.stepKey.startsWith("review_")) assert.ok(item.note, `${item.id} has findings`);
    }
  }
});
