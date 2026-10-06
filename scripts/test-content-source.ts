import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";

const requireFromRepository = createRequire(path.join(process.cwd(), "package.json"));

type Call = { model: string; method: string; authMode: unknown; input: unknown };
const calls: Call[] = [];

function recordingModel(modelName: string, rowsByMethod: Record<string, unknown[]>) {
  return new Proxy(
    {},
    {
      get(_target, method: string) {
        return async (input: unknown, options: { authMode?: unknown } = {}) => {
          calls.push({ model: modelName, method, authMode: options.authMode, input });
          return { data: rowsByMethod[method] ?? [], nextToken: null, errors: null };
        };
      },
    },
  );
}

const plainBodyIr = JSON.parse(readFileSync(path.join(process.cwd(), "scripts", "fixtures", "body-ir", "plain.json"), "utf8"));

const publishedItem = {
  bodyIr: plainBodyIr,
  id: "item-1", type: "article", status: "published", typeStatus: "article#published", slug: "hello",
  headline: "Hello", title: "Hello", versionNumber: 1,
};
const draftItem = { ...publishedItem, status: "draft", typeStatus: "article#draft" };

const clientModels = {
  PublishedItem: recordingModel("PublishedItem", { publishedItemBySlug: [publishedItem], listPublishedItemsByTypeStatusAndPublishedAt: [publishedItem] }),
  PublishedMediaAsset: recordingModel("PublishedMediaAsset", {}),
  PublishedEdition: recordingModel("PublishedEdition", {}),
  PublishedEditionItem: recordingModel("PublishedEditionItem", {}),
  Item: recordingModel("Item", { itemBySlug: [draftItem], listItemsByTypeStatusAndPublishedAt: [draftItem] }),
  MediaAsset: recordingModel("MediaAsset", {}),
  Edition: recordingModel("Edition", {}),
  EditionItem: recordingModel("EditionItem", {}),
};

function injectModule(specifier: string, exports: Record<string, unknown>): void {
  const resolved = requireFromRepository.resolve(specifier);
  requireFromRepository.cache[resolved] = {
    id: resolved, filename: resolved, loaded: true, exports, children: [], paths: [], path: resolved, parent: null,
  } as unknown as NodeJS.Module;
}

injectModule("aws-amplify/data", {
  generateClient: (options: { authMode: string }) => {
    calls.push({ model: "client", method: "generateClient", authMode: options.authMode, input: null });
    return { models: clientModels };
  },
});
injectModule("./lib/amplify-server-runtime.ts", {
  getAmplifyServerRuntime: () => ({
    runWithAmplifyServerContext: async (args: { nextServerContext: unknown; operation: () => Promise<unknown> }) => {
      calls.push({ model: "runtime", method: "nextServerContext", authMode: null, input: args.nextServerContext });
      return args.operation();
    },
  }),
});
injectModule("next/headers", { cookies: () => "cookie-store" });

function loadRepository() {
  for (const key of Object.keys(requireFromRepository.cache)) {
    if (key.includes(`${path.sep}lib${path.sep}graphql-content-repository`) || key.includes(`${path.sep}lib${path.sep}content-source-context`)) {
      delete requireFromRepository.cache[key];
    }
  }
  return requireFromRepository("./lib/graphql-content-repository.ts") as typeof import("../lib/graphql-content-repository");
}

async function main() {
  process.env.SITE_ENV = "production";
  delete process.env.PAPYRUS_CONTENT_SOURCE;
  let { graphqlContentRepository } = loadRepository();
  calls.length = 0;
  const published = await graphqlContentRepository.getArticle("hello");
  assert.ok(published, "published article should load");
  const publishedLookup = calls.find((call) => call.method === "publishedItemBySlug");
  assert.ok(publishedLookup, "published mode must call PublishedItem.publishedItemBySlug");
  assert.equal(publishedLookup.model, "PublishedItem");
  assert.equal(publishedLookup.authMode, "identityPool");
  assert.equal(calls.some((call) => call.model === "Item"), false, "published mode must not touch Item");
  assert.deepEqual(calls.find((call) => call.method === "nextServerContext")?.input, null);

  process.env.SITE_ENV = "staging";
  process.env.PAPYRUS_CONTENT_SOURCE = "drafts";
  ({ graphqlContentRepository } = loadRepository());
  calls.length = 0;
  const draft = await graphqlContentRepository.getArticle("hello");
  const draftLookup = calls.find((call) => call.method === "itemBySlug");
  assert.ok(draftLookup, "drafts mode must call Item.itemBySlug");
  assert.equal(draftLookup.model, "Item");
  assert.equal(draftLookup.authMode, "userPool");
  assert.equal(calls.some((call) => call.model === "PublishedItem"), false, "drafts mode must not touch PublishedItem");
  assert.ok(draft, "a draft article is returned in drafts mode");
  assert.equal(calls.find((call) => call.method === "generateClient")?.authMode, "userPool");
  assert.deepEqual(calls.find((call) => call.method === "nextServerContext")?.input, { cookies: requireFromRepository("next/headers").cookies });

  calls.length = 0;
  await graphqlContentRepository.listArticleSlugs();
  const listed = calls.filter((call) => call.method === "listItemsByTypeStatusAndPublishedAt").map((call) => (call.input as { typeStatus: string }).typeStatus).sort();
  assert.deepEqual(listed, ["article#draft", "article#published"]);

  const cached = requireFromRepository("./lib/cached-content-repository.ts") as typeof import("../lib/cached-content-repository");
  let loaderRuns = 0;
  const originalGetArticle = graphqlContentRepository.getArticle;
  graphqlContentRepository.getArticle = async () => { loaderRuns += 1; return undefined; };
  await cached.getCachedArticle("hello");
  await cached.getCachedArticle("hello");
  graphqlContentRepository.getArticle = originalGetArticle;
  assert.equal(loaderRuns, 2, "drafts reads must never be cached");

  console.log("content-source tests passed");
}

main().catch((error) => { console.error(error); process.exit(1); });
