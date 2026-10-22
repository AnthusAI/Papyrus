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
    NewsroomSection: {
      get: async ({ id }) => ({ data: data.records.NewsroomSection[id] ?? null }),
      list: async () => ({ data: Object.values(data.records.NewsroomSection) as EditorialRecord[] }),
      listNewsroomSectionsByTenantAndSortOrder: async ({ tenantId }) => ({ data: (Object.values(data.records.NewsroomSection) as EditorialRecord[]).filter(row => row.tenantId === tenantId) }),
    },
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
  // PPY-2c4b56: an item stores its section as an id, a slug or a name; resolve by id, then slug, then name, within the publication.
  const sectioned = structuredClone(fixture);
  sectioned.records.NewsroomSection['example#arts'] = { id: 'example#arts', tenantId: 'example', title: 'Arts & Culture', shortTitle: 'Arts', updatedAt: '2026-10-18', editorialMission: 'Cover the arts', editorialPolicy: 'Credit the artists' };
  sectioned.records.NewsroomSection['other#arts'] = { ...sectioned.records.NewsroomSection['example#arts'], id: 'other#arts', tenantId: 'other', editorialMission: 'Not ours' };
  for (const row of [...Object.values(sectioned.records.Item).flat(), ...sectioned.stories] as EditorialRecord[]) row.tenantId = 'example';
  const bare = { publicationKey: 'example', endpoint: options.endpoint, tenantId: 'example', readAttachment: options.readAttachment };
  const section = (value: string, extra: Partial<EditorialOptions> = {}) => resolveEditorialContext(client(sectioned), { ...bare, sectionId: value, ...extra });
  const byId = await section('example#arts');
  assert.equal(byId.scope.sectionId, 'example#arts'); assert.equal('requestedSection' in byId.scope, false);
  assert.ok(byId.text.includes('Cover the arts'));
  for (const value of ['arts', 'Arts', 'Arts & Culture', 'arts-culture']) {
    const found = await section(value);
    assert.equal(found.scope.sectionId, 'example#arts', value);
    assert.equal(found.scope.requestedSection, value);
    assert.ok(found.text.includes('Cover the arts') && !found.text.includes('Not ours'));
  }
  const missing = await section('Newsroom How-To', { optionalPublicationDoctrine: true });
  assert.deepEqual(missing.missingSectionConfiguration, ['Newsroom How-To']);
  assert.equal(missing.scope.sectionId, null); assert.equal(missing.scope.requestedSection, 'Newsroom How-To');
  assert.ok(missing.entries.every(value => value.scope !== 'section'));
  await assert.rejects(section('Newsroom How-To'), /NewsroomSection not found: Newsroom How-To/);
  const twin = structuredClone(sectioned); twin.records.NewsroomSection['example#a1'] = { ...twin.records.NewsroomSection['example#arts'], id: 'example#a1', title: 'Culture Desk' };
  twin.records.NewsroomSection['example#a2'] = { ...twin.records.NewsroomSection['example#arts'], id: 'example#a2', title: 'Culture Desk' };
  await assert.rejects(resolveEditorialContext(client(twin), { ...bare, sectionId: 'Culture Desk' }), /ambiguous/);
  const fallback = structuredClone(fixture); fallback.attachments = [];
  const brief = await resolveEditorialContext(client(fallback), options);
  assert.ok(brief.warnings.some(warning => warning.includes('summary')));
  assert.ok(!JSON.stringify(pack).includes('Old snapshot'));
  console.log("Editorial GraphQL contract: Python parity, revision selection, pagination, explicit fallbacks, budget, publication/tenant scope, attachments and read failures passed");
}
void main().catch(error => { console.error(error); process.exitCode = 1; });
