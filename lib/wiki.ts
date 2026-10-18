import type { SemanticNodeRecord } from "./category-repository";

/** The wiki's front page is an ordinary content item with this slug; its Markus body holds the dynamic components. */
export const WIKI_INDEX_SLUG = "wiki-index";
export const WIKI_PAGE_ITEM_TYPE = "wiki_page";
export const WIKI_CONCEPT_LINK_SCHEME = "concept:";

export const DEFAULT_WIKI_INDEX_MARKUS = `# Concept wiki

Every page in this wiki is a concept: an entity in the knowledge graph that the newsroom has reported on, researched or cited. Open one to see what it is, what it connects to, and the references behind it.

## Recently edited

::recent-concepts{limit=10}

## Browse all concepts

::concept-list
`;

export function conceptEditedAt(node: SemanticNodeRecord): string {
  return node.updatedAt ?? node.versionCreatedAt ?? node.createdAt ?? "";
}

export function conceptTitle(node: SemanticNodeRecord): string {
  return node.displayName?.trim() || node.nodeKey;
}

export function conceptId(node: SemanticNodeRecord): string {
  return node.lineageId ?? node.id;
}

export function recentlyEditedConcepts(nodes: readonly SemanticNodeRecord[], options: { limit?: number; kind?: string | null } = {}): SemanticNodeRecord[] {
  const { limit = 10, kind = null } = options;
  return nodes
    .filter(node => !kind || node.nodeKind === kind)
    .slice()
    .sort((left, right) => conceptEditedAt(right).localeCompare(conceptEditedAt(left)) || conceptTitle(left).localeCompare(conceptTitle(right)))
    .slice(0, limit);
}

export function conceptsByTitle(nodes: readonly SemanticNodeRecord[], options: { kind?: string | null; limit?: number | null } = {}): SemanticNodeRecord[] {
  const filtered = nodes.filter(node => !options.kind || node.nodeKind === options.kind).slice().sort((left, right) => conceptTitle(left).localeCompare(conceptTitle(right)));
  return options.limit ? filtered.slice(0, options.limit) : filtered;
}

/** Finds the concept a `concept:<key>` wiki link names, by lineage id, node key or title. */
export function resolveConceptLink(href: string, nodes: readonly SemanticNodeRecord[]): SemanticNodeRecord | null {
  if (!href.startsWith(WIKI_CONCEPT_LINK_SCHEME)) return null;
  const reference = decodeURIComponent(href.slice(WIKI_CONCEPT_LINK_SCHEME.length)).trim().toLowerCase();
  return nodes.find(node => conceptId(node).toLowerCase() === reference || node.nodeKey.toLowerCase() === reference || conceptTitle(node).toLowerCase() === reference) ?? null;
}

export function conceptWikiPath(node: SemanticNodeRecord): string {
  return `/newsroom/concepts/${encodeURIComponent(conceptId(node))}`;
}
