import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { inboundDnsRecordName, resolveInboundEmailSettings } from "../amplify/inbound-email/settings";

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

const inboundEnvironment = {
  PAPYRUS_INBOUND_EMAIL_DOMAIN: "Mail.Example.org",
  PAPYRUS_INBOUND_EMAIL_CORPUS_KEY: "example-corpus",
  PAPYRUS_PUBLIC_SITE_BASE_URL: "https://example.org",
  PAPYRUS_ROUTE53_HOSTED_ZONE_ID: "Z0EXAMPLE",
  PAPYRUS_ROUTE53_HOSTED_ZONE_NAME: "example.org.",
};

test("inbound email: every setting is the site's own and a missing one is named", () => {
  const settings = resolveInboundEmailSettings(inboundEnvironment, { manageDomainIdentity: true });
  assert.deepEqual(settings, {
    domain: "mail.example.org",
    corpusKey: "example-corpus",
    publicSiteBaseUrl: "https://example.org",
    dnsZone: { id: "Z0EXAMPLE", name: "example.org" },
  });
  assert.equal(inboundDnsRecordName(settings.domain, "example.org"), "mail");
  for (const name of Object.keys(inboundEnvironment)) {
    const { [name]: _removed, ...rest } = inboundEnvironment;
    assert.throws(() => resolveInboundEmailSettings(rest, { manageDomainIdentity: true }), new RegExp(`${name} is not set`));
  }
  // A site that does not verify the SES domain identity needs no hosted zone.
  const { PAPYRUS_ROUTE53_HOSTED_ZONE_ID: _id, PAPYRUS_ROUTE53_HOSTED_ZONE_NAME: _name, ...withoutZone } = inboundEnvironment;
  assert.equal(resolveInboundEmailSettings(withoutZone, { manageDomainIdentity: false }).dnsZone, undefined);
  assert.throws(() => resolveInboundEmailSettings({ ...inboundEnvironment, PAPYRUS_INBOUND_EMAIL_DOMAIN: "  " }, { manageDomainIdentity: false }), /PAPYRUS_INBOUND_EMAIL_DOMAIN is not set/);
});

test("inbound email: no site's domain, corpus or hosted zone is written into the engine", () => {
  for (const file of ["amplify/site-backend.ts", "amplify/functions/ses-inbound-receive/handler.ts", "amplify/functions/assignment-action/handler.ts", "amplify/inbound-email/settings.ts"]) {
    const source = read(file);
    assert.doesNotMatch(source, /\?\? "p\.apyr\.us"|AI-ML-research|Z10285921B1G7MVRV06W9|"https:\/\/p\.apyr\.us"|\?\? "apyr\.us"/, file);
  }
  const receive = read("amplify/functions/ses-inbound-receive/handler.ts");
  assert.doesNotMatch(receive, /PAPYRUS_INBOUND_EMAIL_(DOMAIN|LOCAL_PARTS|CORPUS_KEY)\s*\?\?/);
});

test("steering workspace: References refresh on open and after the editor's own writes, not by subscription", () => {
  const workspace = read("components/topic-steering-workspace.tsx");
  assert.doesNotMatch(workspace, /referenceSubscriptionClient|referencesRealtime|formatReferencesRealtimeStatusMessage/);
  assert.doesNotMatch(workspace, /typeof \w+\.(onCreate|onUpdate|onDelete)\s*[!=]==\s*"function"/);
  assert.doesNotMatch(workspace, /models\.(Reference|SemanticRelation) as unknown as/);
});
