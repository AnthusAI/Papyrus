/** Offline coverage of the real category-action Lambda's `setReferenceSection` (PPY-b5cb8e): the section changes and nothing about the vote does. */
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";
import { Kind, parse, valueFromASTUntyped } from "graphql";
import { schema } from "../amplify/data/schema";

type RecordValue = Record<string, unknown> & { id: string };
type HandlerEvent = { info: { fieldName: string }; identity: unknown; arguments: Record<string, unknown> };
const root = resolve(import.meta.dirname, "..");
const clone = <T,>(value: T): T => structuredClone(value);

async function main() {
  // Authorization runs in managed AppSync: editors and admins by group, and IAM principals by their IAM policy (docs/site-hosting.md), like reviewReferenceCuration.
  const document = parse(schema.transform().schema);
  const mutation = document.definitions.find((definition) => definition.kind === Kind.OBJECT_TYPE_DEFINITION && definition.name.value === "Mutation");
  assert.ok(mutation?.kind === Kind.OBJECT_TYPE_DEFINITION);
  const field = mutation.fields?.find((item) => item.name.value === "setReferenceSection");
  const rules = field?.directives?.find((directive) => directive.name.value === "auth")?.arguments?.find((argument) => argument.name.value === "rules");
  assert.ok(rules);
  assert.deepEqual(clone(valueFromASTUntyped(rules.value)), [{ allow: "groups", groups: ["editor", "admin"] }], "the same rule as reviewReferenceCuration");

  const rows = new Map<string, Map<string, RecordValue>>();
  const writes: Array<{ model: string; input: RecordValue }> = [];
  const table = (name: string) => { if (!rows.has(name)) rows.set(name, new Map()); return rows.get(name)!; };
  const model = (name: string) => ({
    get: async ({ id }: { id: string }) => ({ data: clone(table(name).get(id) ?? null) }),
    create: async () => { throw new Error(`setReferenceSection must not create a ${name}`); },
    update: async (input: RecordValue) => {
      assert.ok(table(name).has(input.id));
      table(name).set(input.id, { ...table(name).get(input.id)!, ...clone(input) });
      writes.push({ model: name, input: clone(input) });
      return { data: clone(input) };
    },
  });
  const client = { models: Object.fromEntries(["Reference", "Message", "SemanticRelation", "NewsroomSection"].map((name) => [name, model(name)])) };
  const modules: Record<string, unknown> = {
    "@aws-sdk/client-lambda": { LambdaClient: class { async send() { throw new Error("no network in this test"); } }, InvokeCommand: class {} },
    "node:crypto": crypto,
    "@aws-amplify/backend/function/runtime": { getAmplifyDataClientConfig: async () => ({ resourceConfig: {}, libraryOptions: {} }) },
    "aws-amplify": { Amplify: { configure: () => undefined } },
    "aws-amplify/data": { generateClient: () => client },
    "fixture:model-payloads": { putJsonModelPayload: async () => undefined, putTextModelPayload: async () => undefined, readJsonModelPayload: async () => null },
  };
  const bundle = await build({
    absWorkingDir: root, entryPoints: ["amplify/functions/category-action/handler.ts"], bundle: true, write: false, platform: "node", format: "cjs", logLevel: "silent",
    external: ["@aws-amplify/backend/function/runtime", "aws-amplify", "aws-amplify/data", "@aws-sdk/client-lambda"],
    plugins: [{ name: "offline-payload-storage", setup(builder) { builder.onResolve({ filter: /\/shared\/model-payloads$/ }, () => ({ path: "fixture:model-payloads", external: true })); } }],
  });
  const fixtureModule = { exports: {} as { handler?: (event: HandlerEvent) => Promise<Record<string, unknown>> } };
  runInNewContext(bundle.outputFiles[0].text, {
    module: fixtureModule, exports: fixtureModule.exports, process: { env: {} }, console,
    require: (name: string) => { assert.ok(Object.hasOwn(modules, name), `no unmocked dependency: ${name}`); return modules[name]; },
  });
  const handler = fixtureModule.exports.handler!;
  assert.ok(handler);
  const editor = { sub: "editor-sub", claims: { sub: "editor-sub", email: "editor@example.org", "cognito:groups": ["editor"] } };
  const reader = { sub: "reader-sub", claims: { sub: "reader-sub", email: "reader@example.org", "cognito:groups": ["reader"] } };
  const operator = { userArn: "arn:aws:sts::123456789012:assumed-role/papyrus-authoring/ryan-session" };
  const referenceId = "reference-fixture-v1";
  const invoke = (arguments_: Record<string, unknown>, identity: unknown = editor) =>
    handler({ info: { fieldName: "setReferenceSection" }, identity, arguments: { referenceId, ...arguments_ } });
  const current = () => table("Reference").get(referenceId)!;
  const VOTE = { curationStatus: "accepted", curationStatusKey: "corpus-fixture#accepted", curationStatusUpdatedAt: "2026-11-01T10:00:00.000Z",
    curationStatusUpdatedBy: "editor@example.org via cli", curationStatusReason: "Worth a video page.", curationActorKind: "human",
    curationReasonCode: null, curationShareable: true, curationDecisionRelationId: "prediction-1", starRating: 4, starRatedAt: "2026-11-01T10:05:00.000Z",
    starRatedBy: "editor@example.org", starFeedKey: "corpus-fixture#stars#4", feedStateKey: "corpus-fixture#rated", reviewedFeedKey: "reviewed",
    predictedAcceptProbability: 0.8, updatedAt: "2026-11-01T10:05:00.000Z" };
  table("Reference").set(referenceId, { id: referenceId, lineageId: "reference-fixture", versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", title: "Video", ...VOTE });
  table("NewsroomSection").set("machines-on-machines#security", { id: "machines-on-machines#security", enabled: true, enabledStatus: "enabled" });
  table("NewsroomSection").set("machines-on-machines#retired", { id: "machines-on-machines#retired", enabled: false, enabledStatus: "disabled" });
  const voteNow = () => Object.fromEntries(Object.keys(VOTE).map((key) => [key, current()[key] ?? null]));
  const before = voteNow();

  // 1. An editor sets the section: only the section, who and when are written.
  const set = await invoke({ sectionId: "machines-on-machines#security", agentLabel: "Claude" });
  assert.deepEqual([set.ok, set.changed, set.sectionId, set.previousSectionId, set.status], [true, true, "machines-on-machines#security", null, "accepted"]);
  assert.equal(current().curationSectionId, "machines-on-machines#security");
  assert.equal(current().curationSectionUpdatedBy, "editor@example.org via signed-in (Claude)", "who: the signed-in person, with the plain note of the agent that acted through the session");
  assert.ok(typeof current().curationSectionUpdatedAt === "string");
  assert.deepEqual(Object.keys(writes[0].input).sort(), ["curationSectionActorKind", "curationSectionDecisionRelationId", "curationSectionId", "curationSectionReason",
    "curationSectionUpdatedAt", "curationSectionUpdatedBy", "id"], "only the section and who set it are written");
  assert.deepEqual([current().curationSectionActorKind, current().curationSectionReason, current().curationSectionDecisionRelationId], ["human", null, null], "a person's choice");
  assert.deepEqual(voteNow(), before, "acceptance, note, feedback and rating are identical");
  assert.equal(table("Message").size + table("SemanticRelation").size, 0, "no Message and no relation");

  // 2. The same section again writes nothing.
  const writesSoFar = writes.length;
  assert.equal((await invoke({ sectionId: "machines-on-machines#security" })).changed, false);
  assert.equal(writes.length, writesSoFar);

  // 3. Unknown and disabled sections, and a Reference that is not accepted, are refused before any write.
  await assert.rejects(invoke({ sectionId: "nope" }), /was not found/);
  await assert.rejects(invoke({ sectionId: "machines-on-machines#retired" }), /disabled/);
  await assert.rejects(invoke({}, reader), /Only an editor or administrator/);
  table("Reference").set("reference-pending", { ...current(), id: "reference-pending", curationStatus: "pending", curationSectionId: undefined });
  await assert.rejects(invoke({ referenceId: "reference-pending", sectionId: "machines-on-machines#security" }), /only on an accepted Reference/);
  assert.equal(writes.length, writesSoFar);

  // 4. Clearing removes the section, still without touching the vote.
  const cleared = await invoke({ sectionId: null });
  assert.deepEqual([cleared.changed, cleared.sectionId, cleared.previousSectionId], [true, null, "machines-on-machines#security"]);
  assert.equal(current().curationSectionId, null);
  assert.deepEqual(voteNow(), before);

  // 5. The operator lane (AWS credentials, no sign-in) can do it; it is recorded by role session, not by a name it sends.
  const byOperator = await invoke({ sectionId: "machines-on-machines#security", actorLabel: "Claimed editor" }, operator);
  assert.equal(byOperator.changed, true);
  assert.equal(current().curationSectionUpdatedBy, "Papyrus operator (ryan-session)");
  assert.deepEqual(voteNow(), before);

  assert.equal(current().curationSectionActorKind, "agent", "an operator on AWS credentials is recorded as an agent");

  // 6. The automatic lane (docs/reference-auto-section.md): only the site cyclotron's current section-selector decision for this Reference, and never
  //    over a person. The operator's section above is a person's: the machine is refused quietly and nothing is written.
  table("SemanticRelation").set("decision-1", { id: "decision-1", predicate: "site_decision_is", relationState: "current", subjectLineageId: "reference-fixture",
    classifierId: "site-cyclotron/section-selector-abc", metadata: JSON.stringify({ label: "machines-on-machines#security", classifier: "section-selector-abc" }) });
  table("SemanticRelation").set("decision-fit", { id: "decision-fit", predicate: "site_decision_is", relationState: "current", subjectLineageId: "reference-fixture",
    classifierId: "site-cyclotron/section-fit-security", metadata: JSON.stringify({ label: "fits" }) });
  const machine = (arguments_: Record<string, unknown>) => invoke({ sectionId: "machines-on-machines#security", decisionRelationId: "decision-1", machineReason: "95% sure", ...arguments_ }, operator);
  let writesBefore = writes.length;
  const overPerson = await machine({});
  assert.deepEqual([overPerson.changed, overPerson.skipped], [false, "a person set or cleared this section"]);
  assert.equal(writes.length, writesBefore);
  await invoke({ sectionId: null });   // a person's clear sticks too
  assert.equal((await machine({})).skipped, "a person set or cleared this section");
  assert.equal(current().curationSectionId, null);

  // A Reference nobody tagged: the machine sets it, as itself, with its evidence and decision; and the same decision again writes nothing.
  table("Reference").set("reference-untagged", { ...current(), id: "reference-untagged", curationSectionId: null, curationSectionUpdatedBy: null,
    curationSectionUpdatedAt: null, curationSectionActorKind: null });
  const untagged = (arguments_: Record<string, unknown>) => machine({ referenceId: "reference-untagged", ...arguments_ });
  const tagged = await untagged({});
  assert.deepEqual([tagged.changed, tagged.actorKind, tagged.sectionId], [true, "cyclotron", "machines-on-machines#security"]);
  const row = table("Reference").get("reference-untagged")!;
  assert.deepEqual([row.curationSectionUpdatedBy, row.curationSectionActorKind, row.curationSectionReason, row.curationSectionDecisionRelationId],
    ["auto:cyclotron", "cyclotron", "95% sure", "decision-1"]);
  writesBefore = writes.length;
  assert.equal((await untagged({})).changed, false);
  assert.equal(writes.length, writesBefore);
  // A decision that names another Section, a fit classifier's decision, or another Reference's decision is refused loudly.
  await assert.rejects(untagged({ sectionId: "machines-on-machines#retired" }), /disabled/);
  table("NewsroomSection").set("machines-on-machines#art", { id: "machines-on-machines#art", enabled: true, enabledStatus: "enabled" });
  await assert.rejects(untagged({ sectionId: "machines-on-machines#art" }), /chose machines-on-machines#security/);
  await assert.rejects(untagged({ decisionRelationId: "decision-fit" }), /not this Reference's current section-selector decision/);
  // The machine may clear its own tag; then a person confirming the machine's section makes it theirs.
  assert.equal((await untagged({ sectionId: null })).changed, true);
  assert.equal(table("Reference").get("reference-untagged")!.curationSectionId, null);
  await untagged({});
  const confirmed = await invoke({ referenceId: "reference-untagged", sectionId: "machines-on-machines#security" });
  assert.deepEqual([confirmed.changed, confirmed.actorKind], [true, "human"]);
  assert.equal(table("Reference").get("reference-untagged")!.curationSectionDecisionRelationId, null);
  assert.equal((await untagged({})).skipped, "a person set or cleared this section");
  assert.deepEqual(voteNow(), before, "no lane ever touches the vote");

  console.log("reference section: ok");
}

main().catch((error) => { console.error(error); process.exit(1); });
