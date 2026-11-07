/** Offline integration coverage of the real curation Lambda and its AppSync auth contract. */
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";
import { Kind, parse, valueFromASTUntyped } from "graphql";
import { schema } from "../amplify/data/schema";
import { assertReferenceReviewSaved } from "../lib/reference-review-response";

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
    listReferencesByLineageAndVersion: async ({ lineageId }: { lineageId: string }) => ({ data: [...table(name).values()].filter((row) => row.lineageId === lineageId).map(clone) }),
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
    // setItemStars asks content-actions to refresh listings; this test never rates a Story, so the client is never constructed or used.
    "@aws-sdk/client-lambda": { LambdaClient: class { async send() { throw new Error("no network in this test"); } }, InvokeCommand: class {} },
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
    external: ["@aws-amplify/backend/function/runtime", "aws-amplify", "aws-amplify/data", "@aws-sdk/client-lambda"],
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
  const voteOnReference = () => ({ actorKind: current().curationActorKind, reasonCode: current().curationReasonCode,
    decisionRelationId: current().curationDecisionRelationId, shareable: current().curationShareable });
  table("Reference").set(referenceId, { id: referenceId, lineageId: "reference-fixture", versionNumber: 1,
    versionState: "current", corpusId: "corpus-fixture", title: "Synthetic source", curationStatus: "pending",
    feedStateKey: "corpus-fixture#unrated", predictedAcceptProbability: 0.73, predictionDecidedAt: "2026-10-28T09:00:00.000Z",
    feedArrivalAt: "2026-10-28T08:00:00.000Z", predictionSortKey: `0.730000#2026-10-28T08:00:00.000Z#${referenceId}` });

  const accepted = await invoke({ action: "accept", note: "   " });
  assert.equal(accepted.ok, true);
  assert.equal(current().curationStatus, "accepted");
  assert.equal(current().feedStateKey, "corpus-fixture#rated", "a vote moves the Reference from the unrated feed to the rated feed");
  assert.equal(current().predictedAcceptProbability, 0.73, "a vote leaves the original prediction alone");
  assert.equal(current().predictionSortKey, `0.730000#2026-10-28T08:00:00.000Z#${referenceId}`, "and the Predictions key");
  // The vote also moves the row into the public index (PPY-7f1e54): the partition follows the vote and the sort key keeps the original prediction's place.
  assert.deepEqual([current().publicFeedKey, current().publicOrderKey], ["corpus-fixture#accepted", `p0.730000#2026-10-28T08:00:00.000Z#${referenceId}`], "an accepted Reference is in the accepted public partition");
  const vote = writes.find((write) => write.model === "Reference" && write.operation === "update")!.input;
  for (const untouched of ["predictedAcceptProbability", "predictionDecidedAt", "predictionSortKey", "feedArrivalAt"]) {
    assert.ok(!Object.hasOwn(vote, untouched), `a vote does not write ${untouched}`);
  }
  assert.equal(current().curationStatusReason, null, "blank explanation is optional and persists as null");
  assert.equal(voteOnReference().actorKind, "human");
  assert.equal(table("Message").size + table("SemanticRelation").size, 0, "Messages come only from people: a vote writes no Message and no relation");
  // The newsroom takes the handler's own response as a saved vote: it must not wait for a Message the vote no longer writes.
  assert.doesNotThrow(() => assertReferenceReviewSaved(accepted, referenceId), "an accept without an explanation is reported as saved");

  const explained = await invoke({ action: "accept", note: "  Useful context.  ", decisionRelationId: "prediction-fixture", shareable: false });
  assert.equal(current().curationStatusReason, "Useful context.");
  assert.equal(voteOnReference().decisionRelationId, "prediction-fixture");
  assert.equal(voteOnReference().shareable, false);
  assert.equal(explained.ok, true);
  assert.doesNotThrow(() => assertReferenceReviewSaved(explained, referenceId), "an accept with an explanation is reported as saved");
  assert.throws(() => assertReferenceReviewSaved({ ok: true, referenceId: "another-reference" }, referenceId), /did not match/);
  assert.throws(() => assertReferenceReviewSaved({ ok: false }, referenceId), /was not saved/);
  await invoke({ action: "accept", note: "again" });
  assert.equal(voteOnReference().decisionRelationId, null, "a later vote replaces the details of the earlier one");
  assert.equal(voteOnReference().shareable, null);

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
  assert.equal(voteOnReference().reasonCode, "duplicate");
  assert.equal(current().feedStateKey, "corpus-fixture#rated", "a rejection is a rating too");
  assert.deepEqual([current().publicFeedKey, current().publicOrderKey], [null, null], "a rejected Reference is in no public partition");
  const reopened = await invoke({ action: "reopen" });
  assert.equal(reopened.status, "pending");
  assert.equal(current().feedStateKey, "corpus-fixture#unrated", "reopening puts the Reference back in the unrated feed");
  assert.deepEqual([current().publicFeedKey, current().publicOrderKey], ["corpus-fixture#recommended#2026-10-28", `p0.730000#2026-10-28T08:00:00.000Z#${referenceId}`], "a reopened Reference with a stored prediction of 0.5 or more is recommended on the day it arrived");
  assert.equal(current().predictedAcceptProbability, 0.73);
  const archived = await invoke({ action: "archive" });
  assert.equal(archived.status, "archived");
  assert.equal(current().feedStateKey, null, "an archived Reference is in no feed");
  assert.deepEqual([current().publicFeedKey, current().publicOrderKey], [null, null], "an archived Reference is in no public partition");
  await invoke({ action: "reject", reasonCode: "duplicate" });
  await invoke({ action: "reject", reasonCode: "out_of_scope", note: "Different coverage." });
  assert.equal(current().curationStatusReason, "Different coverage.");

  // With no reason code sent, the editor's own words are read for the code they name, so the
  // scope-training negatives keep arriving from the surfaces that ask for words instead of a chip.
  const written = await invoke({ action: "reject", note: "Out of scope for this publication." });
  assert.equal(current().curationStatus, "rejected");
  assert.equal(current().curationStatusReason, "Out of scope for this publication.", "the words are kept verbatim");
  assert.equal(written.reasonCode, "out_of_scope");
  assert.equal(voteOnReference().reasonCode, "out_of_scope", "the Reference carries the read code");
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
    { accountId: "123456789012", userArn: "arn:aws:sts::123456789012:assumed-role/fixture-agent/session" });
  assert.equal(service.ok, true);
  assert.equal(voteOnReference().actorKind, "agent");
  assert.equal(current().curationDelegation, null, "no delegation is invented");

  // A star rating keeps the Reference in the right star partition (`starFeedKey`), and gives a row with no arrival one, since the index sorts by it.
  const stars = (count: number | null) => handler({ info: { fieldName: "setReferenceStars" }, identity: editor, arguments: { referenceId, stars: count } });
  assert.equal((await stars(4)).ok, true);
  assert.equal(current().starRating, 4);
  assert.equal(current().starFeedKey, "corpus-fixture#stars#4");
  assert.equal(current().feedArrivalAt, "2026-10-28T08:00:00.000Z", "an arrival the row already has is left alone");
  await stars(2);
  assert.equal(current().starFeedKey, "corpus-fixture#stars#2", "the newest rating wins, in the partition for its stars");
  await stars(null);
  assert.deepEqual([current().starRating, current().starRatedBy, current().starFeedKey], [null, null, null], "clearing the rating takes it out of the star index");
  await assert.rejects(stars(6), /stars must be an integer from 1 to 5/);
  table("Reference").set("reference-no-arrival-v1", { id: "reference-no-arrival-v1", lineageId: "reference-no-arrival", versionNumber: 1, versionState: "current",
    corpusId: "corpus-fixture", curationStatus: "pending", createdAt: "2026-10-01T00:00:00Z" });
  await handler({ info: { fieldName: "setReferenceStars" }, identity: editor, arguments: { referenceId: "reference-no-arrival-v1", stars: 5 } });
  const fresh = table("Reference").get("reference-no-arrival-v1")!;
  assert.deepEqual([fresh.starFeedKey, fresh.feedArrivalAt], ["corpus-fixture#stars#5", "2026-10-01T00:00:00.000Z"], "a Reference with no feedArrivalAt gets one, or it would not be in the index");
  assert.equal(current().curationStatus, "accepted", "stars never change the vote");

  // Rating a pending Reference accepts it, by the same person, through the ordinary accept path. Accepted and rejected ones keep their status; clearing changes nothing.
  assert.equal(fresh.curationStatus, "accepted", "any star on a pending Reference accepts it");
  assert.equal(fresh.curationStatusUpdatedBy, "Fixture editor via signed-in", "the acceptance is by the person who rated, with the via note");
  assert.equal(fresh.curationStatusKey, "corpus-fixture#accepted");
  assert.equal(fresh.starRating, 5, "the accept does not drop the rating");
  const rateStatus = async (id: string, status: string, count: number | null) => {
    table("Reference").set(id, { id, lineageId: id, versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", curationStatus: status, createdAt: "2026-10-01T00:00:00Z" });
    const answer = await handler({ info: { fieldName: "setReferenceStars" }, identity: editor, arguments: { referenceId: id, stars: count } }) as { status: string };
    return [answer.status, table("Reference").get(id)!.curationStatus];
  };
  assert.deepEqual(await rateStatus("reference-star-pending-v1", "pending", 1), ["accepted", "accepted"], "even one star accepts");
  assert.deepEqual(await rateStatus("reference-star-rejected-v1", "rejected", 5), ["rejected", "rejected"], "rating a rejected Reference does not flip it");
  assert.deepEqual(await rateStatus("reference-star-accepted-v1", "accepted", 2), ["accepted", "accepted"]);
  assert.deepEqual(await rateStatus("reference-star-clear-v1", "pending", null), ["pending", "pending"], "clearing stars leaves a pending Reference pending");

  // A video moves between the medium lists with its vote; an ordinary page names no medium field at all.
  const videoId = "reference-video-v1";
  table("Reference").set(videoId, { id: videoId, lineageId: "reference-video", versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", curationStatus: "pending",
    medium: "video", mediumFeedKey: "corpus-fixture#video#pending", feedStateKey: "corpus-fixture#unrated", createdAt: "2026-10-01T00:00:00Z" });
  const voteOnVideo = async (action: string) => { await handler({ info: { fieldName: "reviewReferenceCuration" }, identity: editor, arguments: { referenceId: videoId, action, reasonCode: "duplicate" } }); return table("Reference").get(videoId)!.mediumFeedKey; };
  assert.equal(await voteOnVideo("accept"), "corpus-fixture#video#accepted", "an accepted video is in the accepted video list");
  assert.equal(await voteOnVideo("reject"), "corpus-fixture#video#rejected", "a rejected video is in its own list, away from the accepted ones");
  assert.equal(await voteOnVideo("reopen"), "corpus-fixture#video#pending");
  assert.equal(await voteOnVideo("archive"), null, "an archived video is in no medium list");
  const ordinaryWrites = writes.filter((write) => write.model === "Reference" && write.input.id === referenceId);
  assert.ok(ordinaryWrites.every((write) => !Object.hasOwn(write.input, "mediumFeedKey")), "a vote on an ordinary page names no medium key");

  // A row nobody predicted is never public while pending, and a vote on it names no public field; accepting it puts it in with the unscored marker.
  const plainId = "reference-plain-v1";
  table("Reference").set(plainId, { id: plainId, lineageId: "reference-plain", versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", curationStatus: "pending",
    feedStateKey: "corpus-fixture#unrated", createdAt: "2026-10-01T00:00:00Z" });
  const votePlain = (action: string) => handler({ info: { fieldName: "reviewReferenceCuration" }, identity: editor, arguments: { referenceId: plainId, action, reasonCode: "duplicate" } });
  await votePlain("reject");
  const plainWrites = writes.filter((write) => write.model === "Reference" && write.input.id === plainId);
  assert.ok(plainWrites.every((write) => !Object.hasOwn(write.input, "publicFeedKey") && !Object.hasOwn(write.input, "publicOrderKey")), "a vote on a row that is not and will not be public names no public key");
  await votePlain("reopen");
  await votePlain("accept");
  assert.deepEqual([table("Reference").get(plainId)!.publicFeedKey, table("Reference").get(plainId)!.publicOrderKey], ["corpus-fixture#accepted", `n#2026-10-01T00:00:00.000Z#${plainId}`],
    "an accepted row nobody scored is public, after every scored one");

  // Moving a Reference to another corpus: the old version leaves the public index, the new one is keyed for its corpus (with its own id in the sort key)
  // and carries the card copies, which belong to the preview and are read by lineage.
  const movedFrom = "reference-moving-v1";
  table("Reference").set(movedFrom, { id: movedFrom, lineageId: "reference-moving", versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", externalItemId: "item-moving",
    curationStatus: "accepted", feedStateKey: "corpus-fixture#rated", createdAt: "2026-10-01T00:00:00Z", feedArrivalAt: "2026-10-01T00:00:00.000Z", predictedAcceptProbability: 0.4,
    publicFeedKey: "corpus-fixture#accepted", publicOrderKey: `p0.400000#2026-10-01T00:00:00.000Z#${movedFrom}`,
    cardImage: "https://img.example.org/moving.jpg", cardSummary: "A description.", cardSiteName: "Example", cardPageTitle: "A page" });
  const moved = await handler({ info: { fieldName: "moveReferenceCorpus" }, identity: editor, arguments: { referenceId: movedFrom, corpusId: "corpus-other" } }) as unknown as { referenceId: string; status: string };
  assert.equal(moved.status, "moved");
  const oldVersion = table("Reference").get(movedFrom)!;
  assert.deepEqual([oldVersion.versionState, oldVersion.publicFeedKey, oldVersion.publicOrderKey], ["superseded", null, null], "a superseded version is in no public partition");
  const newVersion = table("Reference").get(moved.referenceId)!;
  assert.equal(newVersion.publicFeedKey, "corpus-other#accepted");
  assert.match(String(newVersion.publicOrderKey), new RegExp(`^p0\\.400000#2026-10-01T00:00:00\\.000Z#${moved.referenceId}$`), "the sort key carries the new version's id");
  assert.deepEqual([newVersion.cardImage, newVersion.cardSummary, newVersion.cardSiteName, newVersion.cardPageTitle], ["https://img.example.org/moving.jpg", "A description.", "Example", "A page"], "the card copies move with the Reference");
  const movedPlain = "reference-moving-plain-v1";
  table("Reference").set(movedPlain, { id: movedPlain, lineageId: "reference-moving-plain", versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", externalItemId: "item-plain",
    curationStatus: "pending", feedStateKey: "corpus-fixture#unrated", createdAt: "2026-10-01T00:00:00Z" });
  const plainMove = await handler({ info: { fieldName: "moveReferenceCorpus" }, identity: editor, arguments: { referenceId: movedPlain, corpusId: "corpus-other" } }) as unknown as { referenceId: string };
  assert.ok(!Object.hasOwn(table("Reference").get(plainMove.referenceId)!, "publicFeedKey"), "a row that is not public gets no explicit null: a null on an index key of a new row is not a missing attribute");

  // The typed schema keeps the same declared authorization as the deployed schema.
  const typedSource = readFileSync(resolve(root, "amplify/data/resource.ts"), "utf8");
  const typedMutation = typedSource.slice(typedSource.indexOf("  reviewReferenceCuration:"), typedSource.indexOf("  createCurationDelegation:"));
  assert.match(typedMutation, /allow\.groups\(categoryWriteGroups\)/);
  assert.match(typedSource, /const categoryWriteGroups = \["editor", "admin"\]/);
  console.log("reference review API: real Lambda persistence, validation, revisions, failure recovery and attribution pass; AppSync editor/admin auth schema verified offline");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
