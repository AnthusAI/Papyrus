import assert from "node:assert/strict";
import test from "node:test";
import {
  checklistProgressLabel,
  checklistProgressText,
  formatStepTime,
  projectStoryStepIssues,
  stepActorText,
  stepChangeProblem,
  noteProblem,
  storyStepNotes,
  VISIBLE_STEP_NOTES,
  storyChecklistSummary,
  storyStepsFromItems,
  storyStepBoardConfig,
  summarizeStoryChecklist,
  type StoryStepRecord,
} from "../lib/story-checklist";
import { projectContentItemBoard } from "../lib/newsroom-board";
import { addLocalPreviewStoryStepNote, createLocalPreviewContentItemVersions, createLocalPreviewStoryChecklist, resetLocalPreviewStoryChecklists, setLocalPreviewStoryStep } from "../lib/local-preview-seed";
import { SYSTEM_ITEM_TYPES, isStoryItemType, storyItemTypeFilter } from "../lib/content-item-lifecycle";

const summary = { templateVersion: 2, total: 9, open: 3, done: 3, skipped: 2, not_applicable: 1, requiredOpen: ["draft"] };

function step(key: string, order: number, state: StoryStepRecord["state"], extra: Partial<StoryStepRecord> = {}): StoryStepRecord {
  return { id: `step-s1-${key}`, storyLineageId: "s1", stepKey: key, stepOrder: order, templateVersion: 2, state, notes: [], ...extra };
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
  assert.equal(issues[0].assignee, "AI (agent)");
  assert.deepEqual(issues.map(issue => issue.priority), [2, 1], "a priority names the state, so Kanbus's own card says Done or Open");
  assert.deepEqual(storyStepBoardConfig().statuses.map(status => status.name), ["Open", "Done", "Skipped", "Not applicable"]);
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

test("a step is read from the sub-task Item: the newest version is the step, its entry says who and when", () => {
  const meta = (state: string, entry: Record<string, unknown>) => JSON.stringify({ checklist: { stepKey: "review_search", stepOrder: 8, templateVersion: 2, command: "papyrus stories step --story s1 --step review_search", entry: { state, ...entry } } });
  const items = [
    { id: "step-s1-review_search-v2", lineageId: "step-s1-review_search", versionNumber: 2, type: "sub-task", status: "done", title: "Reviewed for search", parentLineageId: "s1", versionCreatedAt: "2026-11-07T10:00:00Z",
      metadata: meta("done", { at: "2026-11-07T10:00:00Z", actorKind: "person", actorLabel: "Ryan", note: "Reads well in results." }) },
    { id: "step-s1-review_search-v1", lineageId: "step-s1-review_search", versionNumber: 1, type: "sub-task", status: "open", title: "Reviewed for search", parentLineageId: "s1", metadata: meta("open", { at: "2026-11-01T09:00:00Z", actorKind: "system", actorLabel: "Automatically, from the template" }) },
    { id: "story-v1", lineageId: "story", versionNumber: 1, type: "article", status: "draft", title: "Not a step", parentLineageId: null },
  ];
  const [only, ...rest] = storyStepsFromItems(items);
  assert.equal(rest.length, 0, "only sub-tasks are steps");
  assert.deepEqual([only.id, only.stepKey, only.state, only.actorLabel, only.note, only.storyLineageId], ["step-s1-review_search", "review_search", "done", "Ryan", "Reads well in results.", "s1"]);
});

test("the panel's rules are the backend's: a reason to skip or mark not applicable, findings for a review to be done", () => {
  assert.match(stepChangeProblem("outline", "skipped", {}) ?? "", /why/i);
  assert.match(stepChangeProblem("outline", "not_applicable", { reason: "  " }) ?? "", /why/i);
  assert.equal(stepChangeProblem("outline", "skipped", { reason: "Wrote it by hand" }), null);
  assert.match(stepChangeProblem("review_social", "done", {}) ?? "", /note/i);
  assert.equal(stepChangeProblem("review_social", "done", { note: "Card reads well" }), null);
  assert.equal(stepChangeProblem("outline", "done", {}), null, "a step with its own evidence needs no note");
  assert.equal(stepChangeProblem("review_social", "open", {}), null);
});

test("the preview records a change the way the backend does and refuses what it refuses", () => {
  resetLocalPreviewStoryChecklists();
  const lineage = "preview-item-lineage-copywriting-0";
  assert.throws(() => setLocalPreviewStoryStep(lineage, "review_search", "done", {}), /note/i);
  setLocalPreviewStoryStep(lineage, "review_search", "done", { note: "Reads well" });
  const changed = createLocalPreviewStoryChecklist(lineage).find(item => item.stepKey === "review_search")!;
  assert.deepEqual([changed.state, changed.actorKind, changed.note], ["done", "person", "Reads well"]);
  resetLocalPreviewStoryChecklists();
});

test("a sub-task is never a Story: not on the board, not in a listing filter, never counted", () => {
  assert.ok(SYSTEM_ITEM_TYPES.includes("sub-task"));
  assert.equal(isStoryItemType("sub-task"), false);
  assert.equal(isStoryItemType("article"), true);
  assert.deepEqual(storyItemTypeFilter(), { and: SYSTEM_ITEM_TYPES.map(type => ({ type: { ne: type } })) });
  const cards = projectContentItemBoard({
    contentItemVersions: [
      { id: "s1-v1", lineageId: "s1", versionNumber: 1, stage: "copywriting", type: "article", status: "draft", slug: "a", title: "A" },
      { id: "step-s1-outline-v1", lineageId: "step-s1-outline", versionNumber: 1, stage: "copywriting", type: "sub-task", status: "open", slug: "step-s1-outline", title: "Write the outline" },
    ],
  });
  assert.deepEqual(cards.map(card => card.nativeId), ["s1"], "a step that somehow carries a stage still never becomes a card");
});

test("a step's notes are read in the order stored, newest last, and an entry without text is dropped", () => {
  const notes = storyStepNotes([
    { at: "2026-11-07T10:00:00Z", actorKind: "person", actorLabel: "Ryan", text: "First" },
    { at: "2026-11-07T11:00:00Z", actorKind: "agent", actorLabel: "AI", text: "Second\nwith two lines" },
    { at: "2026-11-07T12:00:00Z", actorKind: "person", actorLabel: "Sierra" },
    "not a note",
  ]);
  assert.deepEqual(notes.map(note => [note.actorLabel, note.text]), [["Ryan", "First"], ["AI", "Second\nwith two lines"]]);
  assert.deepEqual(storyStepNotes(undefined), []);
  const [step] = storyStepsFromItems([{ id: "step-s1-outline-v3", lineageId: "step-s1-outline", versionNumber: 3, type: "sub-task", status: "skipped", parentLineageId: "s1",
    metadata: JSON.stringify({ checklist: { stepKey: "outline", stepOrder: 3, entry: { state: "skipped", reason: "Later" }, notes } }) }]);
  assert.deepEqual([step.state, step.reason, step.notes.length], ["skipped", "Later", 2], "a note does not touch the state or the reason");
});

test("a note needs text, and the preview appends it whatever the step's state and never edits an earlier one", () => {
  resetLocalPreviewStoryChecklists();
  const lineage = "preview-item-lineage-copywriting-0";
  const notesOf = (key: string) => createLocalPreviewStoryChecklist(lineage).find(item => item.stepKey === key)!.notes;
  assert.match(noteProblem("   ") ?? "", /note/i);
  assert.equal(noteProblem("Something"), null);
  assert.throws(() => addLocalPreviewStoryStepNote(lineage, "outline", " "), /note/i);
  const before = notesOf("outline").map(note => ({ ...note }));
  addLocalPreviewStoryStepNote(lineage, "outline", "A skipped step can take a note too");   // skipped
  addLocalPreviewStoryStepNote(lineage, "review_social", "An open step can too");
  assert.deepEqual(notesOf("outline").slice(0, before.length), before, "earlier notes are untouched");
  assert.equal(notesOf("outline").at(-1)?.text, "A skipped step can take a note too");
  assert.equal(createLocalPreviewStoryChecklist(lineage).find(item => item.stepKey === "outline")!.state, "skipped", "the state did not change");
  assert.ok(notesOf("review_people").length > VISIBLE_STEP_NOTES, "the preview has a crowded step to fold");
  resetLocalPreviewStoryChecklists();
});
