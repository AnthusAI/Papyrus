import assert from "node:assert/strict";
import {
  ContentActionFailure,
  createContentActionsClient,
  type ContentActionsTransport,
} from "../lib/content-actions-client";

const seen: { name: string; input: string; authMode: string }[] = [];
const respond = (name: string, data: unknown) => async (args: { input: string }, options: { authMode: string }) => {
  seen.push({ name, input: args.input, authMode: options.authMode });
  return { data };
};

async function main() {
  const transport = {
    queries: {
      deriveMarkus: async (args: { input: string }, options: { authMode: "userPool" }) => {
        seen.push({ name: "deriveMarkus", input: args.input, authMode: options.authMode });
        const request = JSON.parse(args.input);
        if (request.bodyMarkus === "bad") {
          return { data: JSON.stringify({ ok: false, errors: [{ code: "markus-syntax", message: "oops", line: 3 }] }) };
        }
        return { data: JSON.stringify({ ok: true, bodyIrBytes: 12, errors: [] }) };
      },
    },
    mutations: {
      saveItemDraft: respond("saveItemDraft", { ok: true, item: { id: "i", contentHash: "sha256:x", status: "draft", slug: "s", versionNumber: 1 } }),
      publishItem: respond("publishItem", JSON.stringify({ ok: true, changed: true, publishedId: "published-i", versionNumber: 2 })),
      unpublishItem: respond("unpublishItem", JSON.stringify({ ok: true, changed: true })),
    },
  } as unknown as ContentActionsTransport;
  const client = createContentActionsClient(transport);

  const derived = await client.deriveMarkus({ frontMatterYaml: "title: T\n", bodyMarkus: "Hello" });
  assert.equal(derived.bodyIrBytes, 12);
  assert.deepEqual(JSON.parse(seen[0].input), { frontMatterYaml: "title: T\n", bodyMarkus: "Hello" });
  assert.equal(seen[0].authMode, "userPool");

  await assert.rejects(
    () => client.deriveMarkus({ frontMatterYaml: null, bodyMarkus: "bad" }),
    (error: unknown) =>
      error instanceof ContentActionFailure && error.errors[0].code === "markus-syntax" && error.errors[0].line === 3,
  );

  const saved = await client.saveItemDraft({
    id: null, type: "article", slug: "s", section: "articles", frontMatterYaml: null, bodyMarkus: "x", aliases: [], expectedContentHash: null,
  });
  assert.equal(saved.item.contentHash, "sha256:x");

  const published = await client.publishItem("i");
  assert.equal(published.versionNumber, 2);
  assert.deepEqual(JSON.parse(seen.find((call) => call.name === "publishItem")!.input), { id: "i" });

  const unpublished = await client.unpublishItem("i");
  assert.equal(unpublished.changed, true);
  console.log("content-actions-client: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
