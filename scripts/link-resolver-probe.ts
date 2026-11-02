// Resolves the labels of a Reference's links with a counting fake network and prints how many requests it made. Used by features_backend/related-links-requests.feature.
import { createLinkResolver } from "../lib/reference-links-resolve";

const input = JSON.parse(process.argv[2] ?? "{}") as { nodes: number; links: number; references: number };
const counts = { concepts: 0, references: 0, all: 0 };
const resolve = createLinkResolver({
  conceptByLineage: async (lineageId) => { counts.concepts += 1; return { id: `${lineageId}-v1`, lineageId, nodeKey: `topic--${lineageId}`, nodeKind: "topic", displayName: lineageId } as never; },
  referenceByLineage: async (lineageId) => { counts.references += 1; return { id: `${lineageId}-v1`, lineageId, title: lineageId } as never; },
});
async function main() {
  const lookup = await resolve({
    concepts: Array.from({ length: input.links }, (_, number) => `concept-${number}`),
    references: Array.from({ length: input.references }, (_, number) => `reference-${number}`),
  });
  console.log(JSON.stringify({ ...counts, labelled: lookup("concept", "concept-0")?.title ?? null, sitesNodes: input.nodes }));
}
void main();
