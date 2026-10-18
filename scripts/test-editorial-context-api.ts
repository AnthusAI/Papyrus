import assert from "node:assert/strict";
import { resolveAssignmentDoctrine } from "../amplify/functions/shared/editorial-context";

async function main() {
  const rows = (kind: string) => [{ type: "doctrine", status: "private", versionState: "superseded", body: ["Old"] }, { type: "doctrine", status: "private", versionState: "current", body: [`Current ${kind}`] }];
  const client = { models: {
    Item: { itemBySlug: async ({ slug }: { slug: string }) => ({ data: rows(slug), nextToken: null }) },
    NewsroomSection: { get: async ({ id }: { id: string }) => ({ data: { id, editorialMission: "Section mission", editorialPolicy: "Current section", assignmentGuidance: "Current guidance" } }) },
  } };
  const result = await resolveAssignmentDoctrine(client, { sectionKey: "science" });
  assert.equal(result.length, 6);
  assert.equal(result[0].body[0], "Current editorial-doctrine-mission");
  assert.equal(result[3].body[0], "Current section");
  assert.equal(result[4].body[0], "Current guidance");
  assert.ok(!JSON.stringify(result).includes('"Old"'));
  const missing = { models: { ...client.models, Item: { itemBySlug: async () => ({ data: [] }) } } };
  await assert.rejects(resolveAssignmentDoctrine(missing, {}), /expected one current record/);
  const denied = { models: { ...client.models, Item: { itemBySlug: async () => ({ errors: [{ message: "Unauthorized" }] }) } } };
  await assert.rejects(resolveAssignmentDoctrine(denied, {}), /Unauthorized/);
  const ambiguous = { models: { ...client.models, Item: { itemBySlug: async () => ({ data: [rows('x')[1], rows('x')[1]] }) } } };
  await assert.rejects(resolveAssignmentDoctrine(ambiguous, {}), /found 2/);
  const noSection = { models: { ...client.models, NewsroomSection: { get: async () => ({ data: null }) } } };
  await assert.rejects(resolveAssignmentDoctrine(noSection, { sectionKey: "missing" }), /section not found/);
  console.log("Editorial assignment API: current revisions, section parity, missing, ambiguous and denied reads passed");
}
void main().catch(error => { console.error(error); process.exitCode = 1; });
