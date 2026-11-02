/**
 * One content item, one lifecycle: the stages an Item lineage moves through.
 * The default stages mirror CONTENT_ITEM_STAGES in src/papyrus_content/content_item_lifecycle.py;
 * a publication overrides them with SiteBrand.contentItemStages.
 * See docs/content-item-lifecycle.md.
 */
export type ContentItemStageDefinition = {
  key: string;
  label: string;
  /** Closed or rarely visited stage: its board column starts collapsed and its cards load only when it is opened. */
  collapsedUntilOpened?: boolean;
};

/**
 * The Item types that are stories. A story's type is its own attribute, separate from its section (a topic): "article" and "post".
 * Add a type here, and in STORY_ITEM_TYPES in src/papyrus_content/content_item_lifecycle.py. Every other Item type (wiki_page, doctrine, page, and so on) is not a
 * story and never appears on the Stories board or in a story count.
 */
export const STORY_ITEM_TYPES: readonly string[] = ["article", "post"];

export function isStoryItemType(type: string | null | undefined): boolean {
  return typeof type === "string" && STORY_ITEM_TYPES.includes(type);
}

/** The GraphQL `filter` that keeps only story Items, for the Item and PublishedItem list queries. */
export function storyItemTypeFilter(): Record<string, unknown> {
  return STORY_ITEM_TYPES.length === 1
    ? { type: { eq: STORY_ITEM_TYPES[0] } }
    : { or: STORY_ITEM_TYPES.map(type => ({ type: { eq: type } })) };
}

export const PUBLISHED_STAGE_KEY = "published";

/** Stage keys written before the story stages were simplified, read as the stage that replaced them. */
export const LEGACY_CONTENT_ITEM_STAGE_ALIASES: Readonly<Record<string, string>> = {
  research: "reporting",
  report: "reporting",
  editor_select: "reporting",
};

/** Stages for work that has not become a story yet and are not stories-board columns by default; they appear on the assignments board only. */
export const ASSIGNMENT_PHASE_STAGE_KEYS: readonly string[] = ["assignment"];

export const DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS: readonly ContentItemStageDefinition[] = [
  { key: "idea", label: "Idea" },
  { key: "reporting", label: "Reporting" },
  { key: "copywriting", label: "Copywriting" },
  { key: "illustration", label: "Illustration" },
  { key: "typesetting", label: "Typesetting" },
  { key: "spiked", label: "Spiked", collapsedUntilOpened: true },
  { key: "held", label: "Held" },
  { key: "published", label: "Published" },
];

export function contentItemStageKeys(stageDefinitions: readonly ContentItemStageDefinition[]): string[] {
  return stageDefinitions.map(definition => definition.key);
}

export function canonicalContentItemStage(
  stage: string,
  stageDefinitions: readonly ContentItemStageDefinition[] = DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS,
): string {
  const isDefined = stageDefinitions.some(definition => definition.key === stage);
  return isDefined ? stage : LEGACY_CONTENT_ITEM_STAGE_ALIASES[stage] ?? stage;
}

export function legacyStageKeysToLoad(stageDefinitions: readonly ContentItemStageDefinition[]): string[] {
  const definedKeys = contentItemStageKeys(stageDefinitions);
  return Object.entries(LEGACY_CONTENT_ITEM_STAGE_ALIASES)
    .filter(([legacyKey, replacementKey]) => !definedKeys.includes(legacyKey) && definedKeys.includes(replacementKey))
    .map(([legacyKey]) => legacyKey);
}

export function contentItemStageLabel(
  stage: string,
  stageDefinitions: readonly ContentItemStageDefinition[] = DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS,
): string {
  return stageDefinitions.find(definition => definition.key === stage)?.label ?? stage;
}

export type ContentItemVersionRecord = {
  id: string;
  lineageId: string;
  versionNumber: number;
  stage?: string | null;
  type: string;
  status: string;
  title?: string | null;
  headline?: string | null;
  deck?: string | null;
  metadata?: unknown;
  slug: string;
  section?: string | null;
  updatedAt?: string | null;
  /** Who recorded this version; "AI" for machine-written stories. */
  versionCreatedBy?: string | null;
};

export function latestVersionPerContentItem(
  versions: readonly ContentItemVersionRecord[],
): ContentItemVersionRecord[] {
  const latestByLineage = new Map<string, ContentItemVersionRecord>();
  for (const version of versions) {
    const current = latestByLineage.get(version.lineageId);
    if (!current || version.versionNumber > current.versionNumber) latestByLineage.set(version.lineageId, version);
  }
  return [...latestByLineage.values()];
}
