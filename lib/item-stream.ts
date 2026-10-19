import type { EditionContent, EditionSection } from "./content-types";
import { createEditionSectionPlan, createSectionKey } from "./edition-sections";
import { getArticlePublicationItems, type ArticlePublicationItem } from "./publication-items";

export const ITEM_STREAM_RECENT_EDITION_COUNT = 10;
export const ITEM_STREAM_ITEM_LIMIT = 50;

export type ItemStream = {
  items: ArticlePublicationItem[];
  sections: EditionSection[];
  activeSectionKey: string | null;
};

/**
 * Flattens published content into one newest-first stream of articles. The
 * input is ordered newest first; a slug that appears twice keeps its newest entry.
 */
export function selectNewestStreamItems(
  newestFirstContents: EditionContent[],
  limit: number = ITEM_STREAM_ITEM_LIMIT,
): ArticlePublicationItem[] {
  const seenSlugs = new Set<string>();
  const selected: ArticlePublicationItem[] = [];
  for (const content of newestFirstContents) {
    for (const item of getArticlePublicationItems(content.items)) {
      if (seenSlugs.has(item.slug)) continue;
      seenSlugs.add(item.slug);
      selected.push(item);
      if (selected.length >= limit) return selected;
    }
  }
  return selected;
}

/** Builds the stream view: the sections found in the items, and the items filtered by an optional section key. */
export function buildItemStream(items: ArticlePublicationItem[], sectionKey?: string | null): ItemStream {
  const sections = createEditionSectionPlan(items);
  const activeSectionKey = sectionKey ? createSectionKey(sectionKey) : null;
  const activeSection = activeSectionKey ? sections.find((section) => section.key === activeSectionKey) : undefined;
  if (!activeSection) return { items, sections, activeSectionKey: null };
  const itemIds = new Set(activeSection.itemIds);
  return {
    items: items.filter((item) => itemIds.has(item.slug)),
    sections,
    activeSectionKey: activeSection.key,
  };
}
