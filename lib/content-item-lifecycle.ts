/**
 * One content item, one lifecycle: the stages an Item lineage moves through.
 * Mirrors CONTENT_ITEM_STAGES in src/papyrus_content/content_item_lifecycle.py.
 * See docs/content-item-lifecycle.md.
 */
export const CONTENT_ITEM_STAGES = [
  "idea",
  "assignment",
  "research",
  "report",
  "editor_select",
  "copywriting",
  "published",
] as const;

export type ContentItemStage = (typeof CONTENT_ITEM_STAGES)[number];

const CONTENT_ITEM_STAGE_LABELS: Record<ContentItemStage, string> = {
  idea: "Idea",
  assignment: "Assignment",
  research: "Research",
  report: "Report",
  editor_select: "Editor select",
  copywriting: "Copywriting",
  published: "Published",
};

export function contentItemStageLabel(stage: string): string {
  return (CONTENT_ITEM_STAGE_LABELS as Record<string, string>)[stage] ?? stage;
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
