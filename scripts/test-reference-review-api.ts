/** Offline integration coverage of the real curation Lambda and its AppSync auth contract. */
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";
import { Kind, parse, valueFromASTUntyped } from "graphql";
import { schema } from "../amplify/data/schema";

type RecordValue = Record<string, unknown> & { id: string };
type CurationResult = { ok: boolean; status: string; reasonCode: string | null };
type HandlerEvent = { info: { fieldName: string }; identity: unknown; arguments: Record<string, unknown> };
const root = resolve(import.meta.dirname, "..");
const referenceId = "reference-fixture-v1";
const clone = <T,>(value: T): T => structuredClone(value);

async function main() {
  // Authorization runs in managed AppSync before Lambda invocation. Test the
  // actual schema output instead of pretending the Lambda enforces this rule.
  const document = parse(schema.transform().schema);
  const mutation = document.definitions.find((definition) => definition.kind === Kind.OBJECT_TYPE_DEFINITION && definition.name.value === "Mutation");
  assert.ok(mutation?.kind === Kind.OBJECT_TYPE_DEFINITION);
  const review = mutation.fields?.find((field) => field.name.value === "reviewReferenceCuration");
  const auth = review?.directives?.find((directive) => directive.name.value === "auth");
  const rules = auth?.arguments?.find((argument) => argument.name.value === "rules");
  assert.ok(rules);
  assert.deepEqual(clone(valueFromASTUntyped(rules.value)), [{ allow: "groups", groups: ["editor", "admin"] }],
    "only editor/admin groups may invoke curation; no guest, public or general signed-in rule");

  const rows = new Map<string, Map<string, RecordValue>>();
  const payloads = new Map<string, unknown>();
  const writes: Array<{ model: string; operation: string; input: RecordValue }> = [];
  let failReferenceUpdate = false;
  const table = (name: string) => {
    if (!rows.has(name)) rows.set(name, new Map());
    return rows.get(name)!;
  };
  const model = (name: string) => ({
    get: async ({ id }: { id: string }) => ({ data: clone(table(name).get(id) ?? null) }),
    create: async (input: RecordValue) => {
      assert.ok(!table(name).has(input.id), `append-only create must not replace ${name} ${input.id}`);
      table(name).set(input.id, clone(input));
      writes.push({ model: name, operation: "create", input: clone(input) });
      return { data: clone(input) };
    },
    update: async (input: RecordValue) => {
      if (name === "Reference" && failReferenceUpdate) return { data: null, errors: [{ message: "fixture update refused" }] };
      assert.ok(table(name).has(input.id), `update needs an existing ${name}`);
      const next = { ...table(name).get(input.id)!, ...clone(input) };
      table(name).set(input.id, next);
      writes.push({ model: name, operation: "update", input: clone(input) });
      return { data: clone(next) };
    },
  });
  const client = { models: Object.fromEntries(["Reference", "Message", "SemanticRelation", "KnowledgeRawPayload", "NewsroomSection"].map((name) => [name, model(name)])) };
  const payloadKey = (kind: string, id: string, role: string, payloadKind: string) => JSON.stringify([kind, id, role, payloadKind]);
  const writePayload = async (_client: unknown, owner: { ownerKind: string; ownerId: string }, role: string, payloadKind: string, value: unknown) => {
    payloads.set(payloadKey(owner.ownerKind, owner.ownerId, role, payloadKind), clone(value));
  };
  const modules: Record<string, unknown> = {
    "node:crypto": crypto,
    "@aws-amplify/backend/function/runtime": { getAmplifyDataClientConfig: async () => ({ resourceConfig: {}, libraryOptions: {} }) },
    "aws-amplify": { Amplify: { configure: () => undefined } },
    "aws-amplify/data": { generateClient: () => client },
    "fixture:model-payloads": {
      putJsonModelPayload: writePayload,
      putTextModelPayload: writePayload,
      readJsonModelPayload: async (_client: unknown, kind: string, id: string, role: string, payloadKind: string) => clone(payloads.get(payloadKey(kind, id, role, payloadKind)) ?? null),
    },
  };
  const bundle = await build({
    absWorkingDir: root, entryPoints: ["amplify/functions/category-action/handler.ts"],
    bundle: true, write: false, platform: "node", format: "cjs", logLevel: "silent",
    external: ["@aws-amplify/backend/function/runtime", "aws-amplify", "aws-amplify/data"],
    plugins: [{ name: "offline-payload-storage", setup(builder) {
      builder.onResolve({ filter: /\/shared\/model-payloads$/ }, () => ({ path: "fixture:model-payloads", external: true }));
    } }],
  });
  const fixtureModule = { exports: {} as { handler?: (event: HandlerEvent) => Promise<CurationResult> } };
  runInNewContext(bundle.outputFiles[0].text, {
    module: fixtureModule, exports: fixtureModule.exports, process: { env: {} }, console,
    require: (name: string) => {
      assert.ok(Object.hasOwn(modules, name), `no unmocked cloud or network dependency: ${name}`);
      return modules[name];
    },
  });
  assert.ok(fixtureModule.exports.handler);
  const handler = fixtureModule.exports.handler;
  const editor = { sub: "fixture-editor", claims: { sub: "fixture-editor", name: "Fixture editor", "cognito:groups": ["editor"] } };
  const invoke = (arguments_: Record<string, unknown>, identity: unknown = editor) => handler({
    info: { fieldName: "reviewReferenceCuration" }, identity, arguments: { referenceId, ...arguments_ },
  });
  const current = () => table("Reference").get(referenceId)!;
  // A vote is recorded on the Reference itself, so its details are read from the Reference right after the call.
  const vote = () => ({ actorKind: current().curationActorKind, reasonCode: current().curationReasonCode,
    decisionRelationId: current().curationDecisionRelationId, shareable: current().curationShareable });
  table("Reference").set(referenceId, { id: referenceId, lineageId: "reference-fixture", versionNumber: 1,
    versionState: "current", corpusId: "corpus-fixture", title: "Synthetic source", curationStatus: "pending" });

  const accepted = await invoke({ action: "accept", note: "   " });
  assert.equal(accepted.ok, true);
  assert.equal(current().curationStatus, "accepted");
  assert.equal(current().curationStatusReason, null, "blank explanation is optional and persists as null");
  assert.equal(vote().actorKind, "human");
  assert.equal(table("Message").size + table("SemanticRelation").size, 0, "Messages come only from people: a vote writes no Message and no relation");

  const explained = await invoke({ action: "accept", note: "  Useful context.  ", decisionRelationId: "prediction-fixture", shareable: false });
  assert.equal(current().curationStatusReason, "Useful context.");
  assert.equal(vote().decisionRelationId, "prediction-fixture");
  assert.equal(vote().shareable, false);
  assert.equal(explained.ok, true);
  await invoke({ action: "accept", note: "again" });
  assert.equal(vote().decisionRelationId, null, "a later vote replaces the details of the earlier one");
  assert.equal(vote().shareable, null);

  await invoke({ action: "accept", note: "" });
  assert.equal(current().curationStatusReason, null, "clearing a saved explanation is persisted");
  const beforeRejection = writes.length;
  await assert.rejects(invoke({ action: "reject" }), /needs a reason/);
  await assert.rejects(invoke({ action: "reject", note: "   " }), /needs a reason/, "blank words are no reason");
  await assert.rejects(invoke({ action: "reject", reasonCode: "invented" }), /Unsupported reference rejection reason/);
  assert.equal(writes.length, beforeRejection, "invalid rejection cannot partially change status or append feedback");
  const rejected = await invoke({ action: "reject", reasonCode: "duplicate" });
  assert.equal(current().curationStatus, "rejected");
  assert.equal(current().curationStatusReason, null, "a reason code alone needs no written explanation");
  assert.equal(rejected.reasonCode, "duplicate");
  assert.equal(vote().reasonCode, "duplicate");
  await invoke({ action: "reject", reasonCode: "out_of_scope", note: "Different coverage." });
  assert.equal(current().curationStatusReason, "Different coverage.");

  // With no reason code sent, the editor's own words are read for the code they name, so the
  // scope-training negatives keep arriving from the surfaces that ask for words instead of a chip.
  const written = await invoke({ action: "reject", note: "Out of scope for this publication." });
  assert.equal(current().curationStatus, "rejected");
  assert.equal(current().curationStatusReason, "Out of scope for this publication.", "the words are kept verbatim");
  assert.equal(written.reasonCode, "out_of_scope");
  assert.equal(vote().reasonCode, "out_of_scope", "the Reference carries the read code");
  assert.equal((await invoke({ action: "reject", note: "Excluded by our policy on vendor blogs." })).reasonCode, "policy_exclusion");
  assert.equal((await invoke({ action: "reject", note: "Already have it, and off our beat anyway." })).reasonCode, "duplicate",
    "a mechanical reason wins over scope, so no false training negative is recorded");
  assert.equal((await invoke({ action: "reject", note: "The editor and I decided against it." })).reasonCode, "other",
    "words that name no code are filed under \"other\" rather than guessed at");
  assert.equal((await invoke({ action: "reject", reasonCode: "duplicate", note: "Out of scope." })).reasonCode, "duplicate",
    "a reason code the caller chose is never overridden by the words beside it");

  const beforeFailure = writes.length;
  failReferenceUpdate = true;
  await assert.rejects(invoke({ action: "accept" }), /fixture update refused/);
  assert.equal(writes.length, beforeFailure, "a failed first write cannot report success or append a review");
  failReferenceUpdate = false;
  assert.equal((await invoke({ action: "accept" })).status, "accepted", "retry can recover after the refused write");

  // This direct Lambda fixture checks attribution, not AppSync invocation rights.
  // An IAM identity cannot manufacture a human label through request arguments.
  const service = await invoke({ action: "accept", actorSub: "claimed-editor", actorLabel: "Claimed editor", actorKind: "human" },
    { userArn: "arn:aws:sts::123456789012:assumed-role/fixture-agent/session" });
  assert.equal(service.ok, true);
  assert.equal(vote().actorKind, "agent");
  assert.equal(current().curationDelegation, null, "no delegation is invented");

  // The typed schema keeps the same declared authorization as the deployed schema.
  const typedSource = readFileSync(resolve(root, "amplify/data/resource.ts"), "utf8");
  const typedMutation = typedSource.slice(typedSource.indexOf("  reviewReferenceCuration:"), typedSource.indexOf("  createCurationDelegation:"));
  assert.match(typedMutation, /allow\.groups\(categoryWriteGroups\)/);
  assert.match(typedSource, /const categoryWriteGroups = \["editor", "admin"\]/);
  console.log("reference review API: real Lambda persistence, validation, revisions, failure recovery and attribution pass; AppSync editor/admin auth schema verified offline");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
