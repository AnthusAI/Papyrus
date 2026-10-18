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

export const PUBLISHED_STAGE_KEY = "published";

/** Stage keys written before the story stages were simplified, read as the stage that replaced them. */
export const LEGACY_CONTENT_ITEM_STAGE_ALIASES: Readonly<Record<string, string>> = {
  research: "reporting",
  report: "reporting",
  editor_select: "reporting",
};

/** Stages for work that has not become a story yet; they appear on the assignments board only. */
export const ASSIGNMENT_PHASE_STAGE_KEYS: readonly string[] = ["idea", "assignment"];

export const DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS: readonly ContentItemStageDefinition[] = [
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
  slug: string;
  section?: string | null;
  updatedAt?: string | null;
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
