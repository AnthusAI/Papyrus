/** Offline coverage of `setItemStars` in the real category-action Lambda, and of the schema rules around it: stars are private and never reach published output. */
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";
import { Kind, parse, valueFromASTUntyped } from "graphql";
import { schema } from "../amplify/data/schema";
import { projectContentItemBoard } from "../lib/newsroom-board";

type Row = Record<string, unknown> & { id: string };
type Event = { info: { fieldName: string }; identity: unknown; arguments: Record<string, unknown> };
const root = resolve(import.meta.dirname, "..");
const clone = <T,>(value: T): T => structuredClone(value);
const STAR_FIELDS = ["starRating", "starRatedAt", "starRatedBy"];

function modelFields(source: string, modelName: string): Set<string> {
  const start = new RegExp(`^  ${modelName}: `, "m").exec(source);
  assert.ok(start, `model ${modelName} found`);
  const rest = source.slice(start.index);
  const end = rest.indexOf(".secondaryIndexes");
  return new Set([...(end === -1 ? rest : rest.slice(0, end)).matchAll(/^\s{6}(\w+): a\./gm)].map((match) => match[1]));
}

async function main() {
  // The schema: only editors and admins may rate; Item has the three fields in both schema files; PublishedItem and the draft-preview type never do.
  const document = parse(schema.transform().schema);
  const mutation = document.definitions.find((definition) => definition.kind === Kind.OBJECT_TYPE_DEFINITION && definition.name.value === "Mutation");
  assert.ok(mutation?.kind === Kind.OBJECT_TYPE_DEFINITION);
  const field = mutation.fields?.find((candidate) => candidate.name.value === "setItemStars");
  assert.ok(field, "setItemStars is in the deployed schema");
  const rules = field.directives?.find((directive) => directive.name.value === "auth")?.arguments?.find((argument) => argument.name.value === "rules");
  assert.ok(rules);
  assert.deepEqual(clone(valueFromASTUntyped(rules.value)), [{ allow: "groups", groups: ["editor", "admin"] }], "only editor and admin groups can rate a Story");
  for (const file of ["amplify/data/schema.ts", "amplify/data/resource.ts"]) {
    const source = readFileSync(resolve(root, file), "utf8");
    for (const name of STAR_FIELDS) {
      assert.ok(modelFields(source, "Item").has(name), `Item.${name} is in ${file}`);
      assert.ok(!modelFields(source, "PublishedItem").has(name), `PublishedItem.${name} must not exist in ${file}: stars are never published`);
    }
    assert.match(source, /setItemStars: a/, `${file} declares the mutation`);
  }
  const repository = readFileSync(resolve(root, "lib/graphql-content-repository.ts"), "utf8");
  const graphqlItem = /type GraphQLItem = \{([\s\S]*?)\n\};/.exec(repository)?.[1] ?? "";
  for (const name of STAR_FIELDS) assert.ok(!graphqlItem.includes(name), `GraphQLItem (what pages are built from) never carries ${name}`);

  // The handler, with an in-memory Item table.
  const rows = new Map<string, Row>();
  const writes: Array<{ model: string; operation: string; input: Row }> = [];
  let conflict = false;
  const client = { graphql: async ({ variables }: { variables: { input: Row; condition: Record<string, {eq?: unknown; attributeExists?: boolean}> } }) => {
    const row = rows.get(variables.input.id)!;
    if (conflict) row.starRevision = "other";
    const valid = Object.entries(variables.condition).every(([key, rule]) => rule.attributeExists === false ? row[key] == null : row[key] === rule.eq);
    if (!valid) return { errors: [{ message: "ConditionalCheckFailed" }] };
    rows.set(row.id, { ...row, ...clone(variables.input) });
    return { data: { updateItem: { id: row.id } } };
  }, models: {
    Item: {
      get: async ({ id }: { id: string }) => ({ data: clone(rows.get(id) ?? null) }),
      listItemsByLineageAndVersion: async ({ lineageId }: { lineageId: string }) => ({ data: [...rows.values()].filter((row) => row.lineageId === lineageId).map(clone), nextToken: null }),
      create: async (input: Row) => { writes.push({ model: "Item", operation: "create", input: clone(input) }); return { data: input }; },
      update: async (input: Row) => {
        assert.ok(rows.has(input.id), "update needs an existing Item");
        rows.set(input.id, { ...rows.get(input.id)!, ...clone(input) });
        writes.push({ model: "Item", operation: "update", input: clone(input) });
        return { data: clone(rows.get(input.id)) };
      },
    },
    PublishedItem: {
      get: async () => ({ data: null }),
      update: async (input: Row) => { writes.push({ model: "PublishedItem", operation: "update", input: clone(input) }); return { data: input }; },
      create: async (input: Row) => { writes.push({ model: "PublishedItem", operation: "create", input: clone(input) }); return { data: input }; },
    },
  } };
  // The asynchronous call that asks content-actions to refresh the listings: recorded, never made.
  const invocations: Array<{ functionName: string; type: string; payload: unknown }> = [];
  const environment = { env: {} as Record<string, string> };
  class FakeInvokeCommand { constructor(readonly input: { FunctionName: string; InvocationType: string; Payload: Uint8Array }) {} }
  class FakeLambdaClient {
    async send(command: FakeInvokeCommand) {
      invocations.push({ functionName: command.input.FunctionName, type: command.input.InvocationType, payload: JSON.parse(new TextDecoder().decode(command.input.Payload)) });
      return {};
    }
  }
  const modules: Record<string, unknown> = {
    "@aws-sdk/client-lambda": { LambdaClient: FakeLambdaClient, InvokeCommand: FakeInvokeCommand },
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
  const fixtureModule = { exports: {} as { handler?: (event: Event) => Promise<Record<string, unknown>> } };
  runInNewContext(bundle.outputFiles[0].text, {
    module: fixtureModule, exports: fixtureModule.exports, process: environment, console, TextEncoder,
    require: (name: string) => { assert.ok(Object.hasOwn(modules, name), `no unmocked cloud or network dependency: ${name}`); return modules[name]; },
  });
  const handler = fixtureModule.exports.handler!;
  const editor = { sub: "fixture-editor", claims: { sub: "fixture-editor", email: "fixture@example.test", "cognito:groups": ["editor"] } };
  const stars = (itemId: string, count: number | null) => handler({ info: { fieldName: "setItemStars" }, identity: editor, arguments: { itemId, stars: count } });

  rows.set("story-v1", { id: "story-v1", lineageId: "story", versionNumber: 1, versionState: "superseded", versionCreatedAt: "2026-11-01T09:00:00Z", type: "article", status: "draft", stage: "copywriting", updatedAt: "2026-11-01T09:00:00Z" });
  rows.set("story-v2", { id: "story-v2", lineageId: "story", versionNumber: 2, versionState: "current", versionCreatedAt: "2026-11-01T10:00:00Z", type: "article", status: "published", stage: "published", updatedAt: "2026-11-01T10:00:00Z", publishedAt: "2026-11-01T10:00:00Z" });
  rows.set("page-v1", { id: "page-v1", lineageId: "page", versionNumber: 1, versionState: "current", type: "page", status: "draft" });

  const agent = (expectedStarRevision: string | null, count = 4) => handler({ info: { fieldName: "agentSetItemStars" }, identity: editor,
    arguments: { itemId: "story-v2", lineageId: "story", stars: count, expectedUpdatedAt: "2026-11-01T10:00:00Z", expectedStarRevision } });
  await assert.rejects(handler({ info: { fieldName: "agentSetItemStars" }, identity: {},
    arguments: { itemId: "story-v2", lineageId: "story", stars: 4, expectedUpdatedAt: "2026-11-01T10:00:00Z" } }), /cannot rate Stories/);
  await agent(null);
  assert.equal(rows.get("story-v2")!.starRatedBy, "agent:fixture-editor");
  assert.ok(rows.get("story-v2")!.starRevision);
  conflict = true;
  await assert.rejects(agent(String(rows.get("story-v2")!.starRevision), 5), /stale_revision/);
  assert.equal(rows.get("story-v2")!.starRating, 4);
  conflict = false;
  rows.get("story-v2")!.starRating = null;
  rows.get("story-v2")!.starRatedAt = null;
  rows.get("story-v2")!.starRatedBy = null;
  rows.get("story-v2")!.starRevision = null;

  const first = await stars("story-v1", 4);
  assert.deepEqual([first.ok, first.itemId, first.lineageId, first.stars], [true, "story-v2", "story", 4], "the rating goes on the Story's working record, whichever version was named");
  const row = () => rows.get("story-v2")!;
  assert.equal(row().starRating, 4);
  assert.equal(row().starRatedBy, "fixture@example.test via signed-in", "a signed-in session rates as the person; where it came from is a plain note (no CLI client is named here)");
  assert.ok(typeof row().starRatedAt === "string");
  assert.equal(rows.get("story-v1")!.starRating, undefined, "an older version is not rated");
  assert.deepEqual(writes.map((write) => [write.model, write.operation]), [["Item", "update"]], "a plain update of one row: no new version, no published write");
  assert.deepEqual(Object.keys(writes[0].input).sort(), ["id", ...STAR_FIELDS, "starRevision"].sort(), "only the star fields are written, never stage, status, updatedAt or the content");
  assert.equal(row().stage, "published");
  assert.equal(row().status, "published", "rating a published Story does not unpublish it");
  assert.equal(row().updatedAt, "2026-11-01T10:00:00Z", "rating does not reorder the board, which sorts by update time");

  await stars("story-v2", 2);
  assert.equal(row().starRating, 2, "the newest rating wins");
  await stars("story-v2", null);
  assert.deepEqual([row().starRating, row().starRatedAt, row().starRatedBy], [null, null, null], "clearing removes who and when too");
  await assert.rejects(stars("story-v2", 6), /stars must be an integer from 1 to 5/);
  await assert.rejects(stars("story-v2", 0), /stars must be an integer from 1 to 5/);
  await assert.rejects(stars("page-v1", 3), /Only Stories can be rated/, "a system page is not a Story");
  await assert.rejects(stars("missing", 3), /not found/i);
  for (const stage of ["idea", "reporting", "copywriting", "published", "spiked"]) {
    rows.set("staged-v1", { id: "staged-v1", lineageId: "staged", versionNumber: 1, versionState: "current", type: "article", status: stage === "published" ? "published" : "draft", stage });
    assert.equal((await stars("staged-v1", 5)).ok, true, `a Story at the ${stage} stage can be rated`);
    assert.equal(rows.get("staged-v1")!.stage, stage, "rating never moves the Story to another stage");
  }
  assert.ok(writes.every((write) => write.model === "Item" && write.operation === "update"), "every write was a plain update of an Item row");
  // A site that projects its pages is asked once per rating to refresh the listings; a site that does not is not, and the rating still saves.
  assert.deepEqual(invocations, [], "no projection function is configured, so nobody is called");
  environment.env.PAPYRUS_CONTENT_ACTIONS_FUNCTION = "site-content-actions";
  await stars("story-v2", 5);
  await stars("story-v2", null);
  assert.deepEqual(invocations, [
    { functionName: "site-content-actions", type: "Event", payload: { projectionTask: { task: "story-stars", itemId: "story-v2" } } },
    { functionName: "site-content-actions", type: "Event", payload: { projectionTask: { task: "story-stars", itemId: "story-v2" } } },
  ], "one asynchronous call per rating, naming only the Item version: no star value travels");
  await assert.rejects(stars("story-v2", 9), /stars must be/);
  assert.equal(invocations.length, 2, "a refused rating asks for nothing");
  // The board card carries the rating it was read with; a card read from a published-only row has none to show, which is not the same as unrated.
  const base = { lineageId: "s", versionNumber: 1, stage: "copywriting", type: "article", status: "draft", slug: "s" };
  const board = projectContentItemBoard({ contentItemVersions: [{ ...base, id: "rated-v1", lineageId: "rated", starRating: 4 }, { ...base, id: "unrated-v1", lineageId: "unrated", starRating: null }, { ...base, id: "unknown-v1", lineageId: "unknown" }] });
  assert.deepEqual(board.map((issue) => [issue.nativeId, issue.starRating]), [["rated", 4], ["unrated", null], ["unknown", undefined]]);
  console.log("story stars API: auth, privacy of the schema, rating rules, working-record choice and plain-update behaviour pass");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
