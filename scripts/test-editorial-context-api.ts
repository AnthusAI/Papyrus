import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { assignmentDoctrine, resolveEditorialContext, type EditorialClient, type EditorialOptions, type EditorialRecord } from "../amplify/functions/shared/editorial-context";

// Both runtimes verify this synthetic contract fixture, including content/provenance hashes.
const fixture = JSON.parse(readFileSync(new URL("../procedures/newsroom/tests/fixtures/editorial_context_contract.json", import.meta.url), "utf8"));
const options: EditorialOptions = { publicationKey: "example", endpoint: "https://example.invalid/graphql", assignmentId: "a1", readAttachment: async () => "Investigate primary evidence" };
function client(data = structuredClone(fixture)): EditorialClient {
  return { models: {
    KnowledgeCorpus: { listKnowledgeCorporaByRoleAndName: async () => ({ data: data.corpora }) },
    Item: {
      itemBySlug: async ({ slug }) => ({ data: data.records.Item[slug] ?? [] }),
      itemByTenantSlug: async ({ tenantSlug }) => ({ data: data.records.Item[tenantSlug.split("#").at(-1)] ?? [] }),
      listItemsByLineageAndVersion: async ({ lineageId }) => ({ data: lineageId === "story" ? data.stories : [] }),
    },
    NewsroomSection: { get: async ({ id }) => ({ data: data.records.NewsroomSection[id] ?? null }) },
    Assignment: { get: async ({ id }) => ({ data: data.records.Assignment[id] ?? null }) },
    ModelAttachment: { listModelAttachmentsByOwnerRoleAndSortKey: async () => ({ data: data.attachments }) },
  } };
}
async function rejects(change: (data: any) => void, pattern: RegExp, override: Partial<EditorialOptions> = {}) {
  const data = structuredClone(fixture); change(data);
  await assert.rejects(resolveEditorialContext(client(data), { ...options, ...override }), pattern);
}
async function main() {
  const pack = await resolveEditorialContext(client(), options);
  const { resolvedAt: ignoredTs, ...actual } = pack;
  const expected = fixture.pack;
  assert.ok(ignoredTs);
  assert.deepEqual(actual, expected, "Python and GraphQL must render/hash the same complete provenance contract");
  assert.equal(assignmentDoctrine(pack).length, 6);
  assert.equal(assignmentDoctrine(pack)[3].body[0], "Use primary sources");
  await rejects(d => { d.records.Item['editorial-doctrine-policy'] = []; }, /exactly one current/);
  await rejects(d => { d.records.Item['editorial-doctrine-policy'].push(d.records.Item['editorial-doctrine-policy'][1]); }, /found 2/);
  await rejects(d => { d.records.Item['editorial-doctrine-policy'][1].body = ['   ']; }, /empty/);
  await rejects(d => { d.corpora[0].id = 'knowledge-corpus-other'; }, /publication/);
  await rejects(d => { d.corpora.push(d.corpora[0]); }, /publication/);
  await rejects(d => { d.corpora = []; }, /publication/);
  await rejects(() => {}, /section/, { sectionId: "other" });
  await rejects(() => {}, /story/, { storyLineageId: "other" });
  await rejects(() => {}, /budget/, { maxCharacters: 10 });
  await rejects(d => { d.attachments.push(d.attachments[0]); }, /Ambiguous/);
  await rejects(d => { d.attachments[0].ownerId = 'other'; }, /owner/);
  await rejects(() => {}, /empty/, { readAttachment: async () => " " });
  await rejects(() => {}, /attachment denied/, { readAttachment: async () => { throw new Error("attachment denied"); } });
  await rejects(d => { delete d.records.NewsroomSection.science; }, /not found/);
  for (const target of ['policy', 'story', 'section']) await rejects(d => {
    const row = target === 'policy' ? d.records.Item['editorial-doctrine-policy'][1] : target === 'story' ? d.stories[0] : d.records.NewsroomSection.science;
    row.tenantId = 'other';
  }, /tenant/);
  await rejects(() => {}, /tenant/, { tenantId: 'example' });
  const scoped = structuredClone(fixture);
  for (const row of [...Object.values(scoped.records.Item).flat(), ...scoped.stories, ...Object.values(scoped.records.NewsroomSection)] as EditorialRecord[]) row.tenantId = 'example';
  const scopedClient = client(scoped);
  scopedClient.models.Item.itemBySlug = async () => { throw new Error('Tenant reads must use tenant index'); };
  const tenantPack = await resolveEditorialContext(scopedClient, { ...options, tenantId: 'example' });
  assert.equal(tenantPack.publication.tenantId, 'example');
  const denied = client();
  denied.models.Item.itemBySlug = async () => ({ errors: [{ message: "Unauthorized" }] });
  await assert.rejects(resolveEditorialContext(denied, options), /Unauthorized/);
  const paged = client(); let reads = 0;
  paged.models.Item.itemBySlug = async ({ slug }, args) => {
    reads++;
    return args?.nextToken ? { data: fixture.records.Item[slug] } : { data: [], nextToken: 'next' };
  };
  assert.equal((await resolveEditorialContext(paged, options)).contextHash, pack.contextHash);
  assert.equal(reads, 4);
  // PPY-2c4b56: the editorial check asks for optional publication doctrine; nobody else does.
  const noMission = structuredClone(fixture); noMission.records.Item['editorial-doctrine-mission'] = [];
  await assert.rejects(resolveEditorialContext(client(noMission), options), /Publication mission: expected exactly one current record, found 0/);
  const skipped = await resolveEditorialContext(client(noMission), { ...options, optionalPublicationDoctrine: true });
  assert.deepEqual(skipped.missingPublicationDoctrine, ["mission"]);
  assert.ok(!skipped.entries.some(value => value.scope === "publication" && value.kind === "mission"));
  const optional = await resolveEditorialContext(client(), { ...options, optionalPublicationDoctrine: true });
  assert.equal("missingPublicationDoctrine" in optional, false);
  assert.equal(optional.contextHash, pack.contextHash);
  await rejects(d => { d.records.Item['editorial-doctrine-mission'].push(d.records.Item['editorial-doctrine-mission'].at(-1)); }, /found 2/, { optionalPublicationDoctrine: true });
  const fallback = structuredClone(fixture); fallback.attachments = [];
  const brief = await resolveEditorialContext(client(fallback), options);
  assert.ok(brief.warnings.some(warning => warning.includes('summary')));
  assert.ok(!JSON.stringify(pack).includes('Old snapshot'));
  console.log("Editorial GraphQL contract: Python parity, revision selection, pagination, explicit fallbacks, budget, publication/tenant scope, attachments and read failures passed");
}
void main().catch(error => { console.error(error); process.exitCode = 1; });
