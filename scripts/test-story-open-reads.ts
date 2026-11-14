// What opening a story reads (features/story-open-reads.feature). A fake GraphQL client records every query field; the story has one
// cited Reference, and the relation table holds thousands of other relations that the open must never page through.
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
import type * as TrailClient from "../components/story-reporting-trail-client";

type GraphqlClient = TrailClient.GraphqlClient;
type GraphqlResponse = Awaited<ReturnType<GraphqlClient["graphql"]>>;
const connection = (field: string, items: Record<string, unknown>[], nextToken: string | null = null): GraphqlResponse => ({ data: { [field]: { items, nextToken } } });

// The client module talks to Amplify; bundle it with the Amplify boundary stubbed, so the test passes its own fake client.
let trailClient: Promise<typeof TrailClient> | undefined;
function loadTrailClient(): Promise<typeof TrailClient> {
  trailClient ??= build({
    entryPoints: ["components/story-reporting-trail-client.ts"], bundle: true, write: false, platform: "node", format: "esm", logLevel: "silent", packages: "external",
    plugins: [{ name: "amplify-boundary", setup(builder) {
      builder.onResolve({ filter: /^aws-amplify\/data$|amplify-client-provider$/ }, (args) => ({ path: args.path, namespace: "stub" }));
      builder.onLoad({ filter: /.*/, namespace: "stub" }, () => ({ contents: "export const generateClient = () => { throw new Error('no Amplify in tests'); }; export const configureAmplifyClient = () => undefined;", loader: "js" }));
    } }],
  }).then(async (result) => {
    mkdirSync(".papyrus-runs", { recursive: true });
    const file = path.join(mkdtempSync(path.resolve(".papyrus-runs/story-open-reads-")), "trail-client.mjs");   // inside the project, so its packages resolve
    writeFileSync(file, result.outputFiles[0].text);
    return import(pathToFileURL(file).href) as Promise<typeof TrailClient>;
  });
  return trailClient;
}

function fakeClient() {
  const calls: { field: string; variables: Record<string, unknown> }[] = [];
  const client: GraphqlClient = {
    graphql: async ({ query, variables }): Promise<GraphqlResponse> => {
      const field = /\{\s*(\w+)\s*\(/.exec(String(query))?.[1] ?? "unknown";
      const vars = (variables ?? {}) as Record<string, unknown>;
      calls.push({ field, variables: vars });
      if (field === "listItemsByLineageAndVersion") {
        const versions = [1, 2, 3].map(number => ({ id: `story-a-v${number}`, versionNumber: number, versionState: number === 3 ? "current" : "superseded", stage: "copywriting" }));
        const ordered = String(query).includes("DESC") ? [...versions].reverse() : versions;
        return connection(field, ordered.slice(0, Number(vars.limit ?? 200)));
      }
      if (field === "listSemanticRelationsBySubjectState" && vars.subjectStateKey === "item#story-a#current") {
        return connection(field, [{ id: "rel-1", predicate: "uses_evidence", subjectKind: "item", subjectLineageId: "story-a", objectKind: "reference", objectId: "ref-1", objectLineageId: "ref-1", metadata: JSON.stringify({ role: "cited" }) }]);
      }
      if (field === "listSemanticRelations") {
        // The whole relation table: 5,000 rows, 200 to a page. Reaching this is the cost the open must not pay.
        const offset = vars.nextToken ? Number(vars.nextToken) : 0;
        return connection(field, [], offset + 200 < 5000 ? String(offset + 200) : null);
      }
      if (field === "getReference") return { data: { getReference: { id: "ref-1", title: "A source", sourceUri: "https://example.org/a" } } } as unknown as GraphqlResponse;
      return connection(field, []);
    },
  };
  return { client, calls };
}

test("the editor learns the newest version with one indexed read of one row", async () => {
  const { loadNewestStoryVersion } = await loadTrailClient();
  const { client, calls } = fakeClient();
  assert.deepEqual(await loadNewestStoryVersion("story-a", false, client), { id: "story-a-v3", versionNumber: 3 });
  assert.deepEqual(calls.map(call => call.field), ["listItemsByLineageAndVersion"]);
  assert.equal(calls[0].variables.limit, 1);
  const editor = readFileSync("components/newsroom-article-editor.tsx", "utf8");
  assert.doesNotMatch(editor, /loadStoryReportingTrail/, "the editor no longer loads the whole trail for a version number");
});

test("the story's References come from the subject-state index, not a scan of every relation", async () => {
  const { loadStoryReportingTrail } = await loadTrailClient();
  const { client, calls } = fakeClient();
  const trail = await loadStoryReportingTrail("story-a", "story-a-v3", false, client);
  assert.deepEqual(trail.references.map(reference => [reference.referenceId, reference.role]), [["ref-1", "cited"]]);
  assert.ok(!calls.some(call => call.field === "listSemanticRelations"), "no listSemanticRelations scan");
  const relationReads = calls.filter(call => call.field === "listSemanticRelationsBySubjectState");
  assert.deepEqual(relationReads.map(call => call.variables.subjectStateKey), ["item#story-a#current"]);
});
