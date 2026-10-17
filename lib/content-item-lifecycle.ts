/**
 * One content item, one lifecycle: the stages an Item lineage moves through.
 * The default stages mirror CONTENT_ITEM_STAGES in src/papyrus_content/content_item_lifecycle.py;
 * a publication overrides them with SiteBrand.contentItemStages.
 * See docs/content-item-lifecycle.md.
 */
export type ContentItemStageDefinition = {
  key: string;
  label: string;
};

export const DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS: readonly ContentItemStageDefinition[] = [
  { key: "idea", label: "Idea" },
  { key: "assignment", label: "Assignment" },
  { key: "research", label: "Research" },
  { key: "report", label: "Report" },
  { key: "editor_select", label: "Editor select" },
  { key: "copywriting", label: "Copywriting" },
  { key: "illustration", label: "Illustration" },
  { key: "typesetting", label: "Typesetting" },
  { key: "published", label: "Published" },
];

export function contentItemStageKeys(stageDefinitions: readonly ContentItemStageDefinition[]): string[] {
  return stageDefinitions.map(definition => definition.key);
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
