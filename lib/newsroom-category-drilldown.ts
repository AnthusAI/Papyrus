import { toPublicNewsroomPath } from "./newsroom-base-path";
import type {
  CategorySteeringCategory,
  SemanticRelationRecord,
} from "./category-repository";
import type {
  SemanticNeighborGroup,
  SemanticObjectSummary,
} from "./semantic-graph";

export type CategoryDrilldownContext = {
  aliases: string[];
  categories: CategorySteeringCategory[];
  includeDescendants: boolean;
  primary: CategorySteeringCategory | null;
};

type CategoryGraph = {
  neighbors(kind: string, lineageId: string): SemanticNeighborGroup[];
  referencesForCategory(categoryLineageId: string): SemanticObjectSummary[];
};

export function categoryLineageId(category: CategorySteeringCategory): string {
  return category.lineageId ?? category.id;
}

export function buildCategoryDrilldownContext(categories: CategorySteeringCategory[], selection?: string | null): CategoryDrilldownContext {
  if (!selection) return { aliases: [], categories: [], includeDescendants: false, primary: null };
  const directMatches = uniqueCategoryRecords(categories.filter((category) => matchesCategorySelection(category, selection)));
  const primary = directMatches[0] ?? null;
  const selectedCategoryKey = primary?.categoryKey ?? selection;
  const matchingCategoryKeyRecords = uniqueCategoryRecords(categories.filter((category) => category.categoryKey === selectedCategoryKey));
  const directRecords = uniqueCategoryRecords([...directMatches, ...matchingCategoryKeyRecords]);
  const includeDescendants = directRecords.some((category) => !category.parentCategoryKey);
  const childRecords = includeDescendants
    ? categories.filter((category) => category.parentCategoryKey === selectedCategoryKey)
    : [];
  const records = uniqueCategoryRecords([...directRecords, ...childRecords]);
  return {
    aliases: categoryAliasValues(records),
    categories: records,
    includeDescendants,
    primary: primary ?? records[0] ?? null,
  };
}

export function buildTopicDrilldownContext(
  root: { category: CategorySteeringCategory; subcategorys: CategorySteeringCategory[] },
  selected: CategorySteeringCategory,
  categoryByUid: Map<string, CategorySteeringCategory>,
): CategoryDrilldownContext {
  const selectedFlatCategory = categoryByUid.get(selected.categoryKey) ?? null;
  const directRecords = uniqueCategoryRecords([selected, selectedFlatCategory].filter((category): category is CategorySteeringCategory => Boolean(category)));
  const includeDescendants = selected.categoryKey === root.category.categoryKey;
  const childRecords = includeDescendants ? root.subcategorys : [];
  const records = uniqueCategoryRecords([...directRecords, ...childRecords]);
  return {
    aliases: categoryAliasValues(records),
    categories: records,
    includeDescendants,
    primary: directRecords[0] ?? records[0] ?? null,
  };
}

export function referencesForCategoryContext(graph: CategoryGraph, context: CategoryDrilldownContext): SemanticObjectSummary[] {
  return uniqueSemanticSummaries(context.aliases.flatMap((alias) => graph.referencesForCategory(alias)));
}

export function semanticNodesForCategoryContext(graph: CategoryGraph, context: CategoryDrilldownContext): SemanticObjectSummary[] {
  return uniqueSemanticSummaries(
    context.aliases.flatMap((alias) => graph.neighbors("category", alias))
      .flatMap((group) => group.objects)
      .filter((object) => object.kind === "semanticNode"),
  );
}

export function uniqueNeighborGroupsForCategoryContext(graph: CategoryGraph, context: CategoryDrilldownContext): SemanticNeighborGroup[] {
  const groups = new Map<string, SemanticNeighborGroup>();
  for (const alias of context.aliases) {
    for (const group of graph.neighbors("category", alias)) {
      const key = `${group.direction}#${group.predicate}`;
      const current = groups.get(key);
      if (!current) {
        groups.set(key, { ...group, relations: [...group.relations], objects: [...group.objects] });
      } else {
        current.relations = uniqueRelations([...current.relations, ...group.relations]);
        current.objects = uniqueSemanticSummaries([...current.objects, ...group.objects]);
      }
    }
  }
  return Array.from(groups.values());
}

export function topicHref(rootCategoryKey: string, selectedCategoryKey?: string | null): string {
  const encodedRoot = encodeURIComponent(rootCategoryKey);
  const encodedSelected = selectedCategoryKey && selectedCategoryKey !== rootCategoryKey ? `/${encodeURIComponent(selectedCategoryKey)}` : "";
  return toPublicNewsroomPath(`/newsroom/topics/${encodedRoot}${encodedSelected}`);
}

export function categoryDrilldownHref(section: "references" | "concepts", categoryKey: string): string {
  return toPublicNewsroomPath(`/newsroom/${section}/${encodeURIComponent(categoryKey)}`);
}

function matchesCategorySelection(category: CategorySteeringCategory, selection: string): boolean {
  return category.id === selection || category.lineageId === selection || category.categoryKey === selection;
}

function uniqueCategoryRecords(categories: CategorySteeringCategory[]): CategorySteeringCategory[] {
  const records = new Map<string, CategorySteeringCategory>();
  for (const category of categories) {
    records.set(category.id, category);
  }
  return Array.from(records.values());
}

function categoryAliasValues(categories: CategorySteeringCategory[]): string[] {
  const aliases = new Set<string>();
  for (const category of categories) {
    aliases.add(category.id);
    aliases.add(category.categoryKey);
    if (category.lineageId) aliases.add(category.lineageId);
  }
  return Array.from(aliases).filter(Boolean);
}

function uniqueRelations(relations: SemanticRelationRecord[]): SemanticRelationRecord[] {
  return Array.from(new Map(relations.map((relation) => [relation.id, relation])).values());
}

function uniqueSemanticSummaries(objects: SemanticObjectSummary[]): SemanticObjectSummary[] {
  const map = new Map<string, SemanticObjectSummary>();
  for (const object of objects) map.set(`${object.kind}#${object.lineageId}`, object);
  return Array.from(map.values()).sort((left, right) => left.label.localeCompare(right.label));
}
