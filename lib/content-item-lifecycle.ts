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
 * The Item types that are not Stories: the fixed system set, the same list as SYSTEM_ITEM_TYPES in src/papyrus_content/content_item_lifecycle.py (change both;
 * scripts/test-story-types.ts and procedures/newsroom/tests/test_story_types.py keep them equal). Every other Item type is a Story type, so a site's own new type
 * (`guide`, `case-study`) needs no engine change. A system type never appears on the Stories board or in a story count. Which Story types a site offers editors,
 * and which one is its default, come from the site's projection.json (lib/site-story-types.ts).
 */
export const SYSTEM_ITEM_TYPES: readonly string[] = ["wiki_page", "doctrine", "page", "sub-task"];

/**
 * The stored type of a Story that has none yet (UNTYPED_ITEM_TYPE in content_item_lifecycle.py). `Item.type` is required and `typeStatus` is a key, so "no type" is an
 * explicit value. It is a Story type like any other for the board; the editor shows it as "not set", and a Story of this type cannot be published.
 */
export const UNTYPED_ITEM_TYPE = "untyped";

export function isUntyped(type: string | null | undefined): boolean {
  return type === UNTYPED_ITEM_TYPE;
}

export function isStoryItemType(type: string | null | undefined): boolean {
  return typeof type === "string" && type !== "" && !SYSTEM_ITEM_TYPES.includes(type);
}

/** The GraphQL `filter` that keeps only story Items, for the Item and PublishedItem list queries: the type is not any system type. */
export function storyItemTypeFilter(): Record<string, unknown> {
  return { and: SYSTEM_ITEM_TYPES.map(type => ({ type: { ne: type } })) };
}

/**
 * The filter for the board's stage columns: story types, and never a superseded version. A saved version keeps the stage it was written in, so a Story
 * published long ago still has a superseded row in Copywriting; the Published column loads only its newest page, and that row would stand in for the Story
 * in the wrong column. The newest row of a Story is current or a draft.
 */
export function boardStoryFilter(): Record<string, unknown> {
  return { and: [...SYSTEM_ITEM_TYPES.map(type => ({ type: { ne: type } })), { versionState: { ne: "superseded" } }] };
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
  /** An editor's private 1-5 rating of the Story. Absent (undefined) when this record was not read from the Item row, so the rating is unknown; null is unrated. */
  starRating?: number | null;
  /** current, draft or superseded. Read by the board's stage queries; absent on records built elsewhere. */
  versionState?: string | null;
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
