// Types a hashtag the way the backend sees it (in memory) and prints what was written. Used by features_backend/editor-concepts.feature.
import { actingFor, buildEventTenantContext } from "../amplify/functions/shared/tenant-context";
import { createReferenceLink, describeEditorConcept, type ReferenceLinkStore } from "../amplify/functions/category-action/reference-links";

const input = JSON.parse(process.argv[2] ?? "{}") as { names: string[]; describe?: string };
const nodes = new Map<string, Record<string, any>>();
const relations = new Map<string, Record<string, any>>();
const store: ReferenceLinkStore & { updateSemanticNode(node: Record<string, unknown>): Promise<void> } = {
  getCurrentReference: async (id) => ({ id: `${id}-v1`, lineageId: id, versionNumber: 1 }),
  getSemanticNode: async (id) => (nodes.get(id) as never) ?? null,
  createSemanticNode: async (node) => { if (nodes.has(node.lineageId as string)) return false; nodes.set(node.lineageId as string, node); return true; },
  updateSemanticNode: async (node) => { for (const [key, value] of nodes) if (value.id === node.id) nodes.set(key, { ...value, ...node }); },
  getRelation: async (id) => (relations.get(id) as never) ?? null,
  putRelation: async (relation) => { relations.set(relation.id as string, relation); },
};
async function main() {
  for (const name of input.names) await createReferenceLink(store, { subjectLineageId: "reference-1", objectKind: "semanticNode", objectLineageId: "x", predicate: "tagged_with", newConceptName: name, callerSub: "editor-1", now: "2026-11-02T12:00:00Z" });
  if (input.describe) await describeEditorConcept(store, { lineageId: [...nodes.keys()][0], description: input.describe, callerSub: "editor-2", now: "2026-11-02T13:00:00Z" });
  console.log(JSON.stringify({ nodes: [...nodes.values()], relations: [...relations.values()].map((row) => ({ ...row, metadata: JSON.parse(row.metadata) })) }));
}
// The helpers read the tenant of the call they run in: one call on a dedicated stack with no tenant, as the sites are today.
void actingFor(buildEventTenantContext({ identity: { sub: "probe", claims: {} } }, {}), main);
