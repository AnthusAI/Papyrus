import type { Article } from "./articles";
import type { EditionSection } from "./content-types";
import { createEditionSectionPlan, createSectionKey } from "./edition-sections";
import { articleToPublicationItem, type ArticlePublicationItem } from "./publication-items";

export const ITEM_STREAM_ITEM_LIMIT = 50;

export type ItemStream = {
  items: ArticlePublicationItem[];
  sections: EditionSection[];
  activeSectionKey: string | null;
};

/**
 * The stream's items from the newest published articles, newest first (the order the item index returns them).
 * A slug that appears twice keeps its newest entry.
 */
export function articlesToStreamItems(newestFirstArticles: Article[], limit: number = ITEM_STREAM_ITEM_LIMIT): ArticlePublicationItem[] {
  const seenSlugs = new Set<string>();
  const selected: ArticlePublicationItem[] = [];
  for (const article of newestFirstArticles) {
    if (seenSlugs.has(article.slug)) continue;
    seenSlugs.add(article.slug);
    selected.push(articleToPublicationItem(article));
    if (selected.length >= limit) break;
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
