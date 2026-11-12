import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const root = join(__dirname, "..");
const read = (file: string) => readFileSync(join(root, file), "utf8");

test("console chat client: no schema probing", () => {
  const chat = read("lib/console-chat-client.ts");
  assert.doesNotMatch(chat, /__type|__schema|introspection/i);
  assert.doesNotMatch(chat, /_LEGACY\b/);
  assert.doesNotMatch(chat, /schemaFields|SchemaSnapshot|SELECTION_CANDIDATES|isUnavailableQueryError/);
  assert.doesNotMatch(chat, /typeof \w+\.(onCreate|onUpdate)\s*[!=]==\s*"function"/);
});

test("console chat client: one credential", () => {
  const chat = read("lib/console-chat-client.ts");
  assert.doesNotMatch(chat, /apiKey|API_KEY/);
  assert.doesNotMatch(chat, /catch \((first|second)Error\)/);
});

test("console chat client: failures are raised", () => {
  const chat = read("lib/console-chat-client.ts");
  assert.doesNotMatch(chat, /deriveConsoleThreadsFromMessages/);
  assert.doesNotMatch(chat, /hasExplicitThreadIds/);
  assert.doesNotMatch(chat, /allowPartialData/);
  assert.doesNotMatch(chat, /Fall back to/i);
});

test("content repository: one edition index", () => {
  const repository = read("lib/graphql-content-repository.ts");
  assert.doesNotMatch(repository, /typeof \w+\.listPublishedEditionsByStatusAndPublishedAt/);
  assert.doesNotMatch(repository, /getEditionPublishedAtIndexQuery|isMissingPublishedAtIndexError/);
  assert.match(repository, /getPublishedEditionModel\(\)\.listPublishedEditionsByStatusAndPublishedAt/);
});

test("content repository: a layout plan is validated as written", () => {
  const repository = read("lib/graphql-content-repository.ts");
  assert.doesNotMatch(repository, /pruneLayoutPlanUnavailableItems|sanitizedLayoutPlan|Pruned/);
  assert.doesNotMatch(repository, /getFallbackImage|Fallback editorial image/);
  assert.match(repository, /validateEditionLayoutPlanForItems\(layoutPlan, items,/);
});

test("news desk client: References come from their indexes", () => {
  const client = read("components/news-desk-taxonomy-client.ts");
  assert.doesNotMatch(client, /loadReferencePageByFallbackList|loadReferencePageByLegacyFeed|LIST_REFERENCES_FALLBACK_QUERY/);
  assert.doesNotMatch(client, /isMissingGraphQLQueryFieldError|falling back to legacy/);
  assert.match(client, /if \(order === "imported"\) return loadReferencePageByImportedFeed\(options\);/);
});

test("newsroom sections: one source for names and lists", () => {
  const workspace = read("components/topic-steering-workspace.tsx");
  const sections = read("lib/newsroom-sections.ts");
  assert.doesNotMatch(workspace, /SHORT_TITLE_FALLBACKS|normalizeNewsroomSectionsWithFallback|fallbackNewsroomSections|needsSectionFallback|needsProposalFallback/);
  assert.doesNotMatch(sections, /SHORT_TITLE_FALLBACKS/);
  assert.doesNotMatch(workspace, /Creative Work|Market Structure/);
  assert.match(sections, /return section\.shortTitle\?\.trim\(\) \|\| section\.title;/);
});
