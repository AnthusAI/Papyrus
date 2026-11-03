"use client";

import { isLocalPreviewEnabled } from "../lib/local-preview";
import { previewVersionIdForLineage } from "../lib/local-preview-seed";
import { resolveArticlesBackend } from "../lib/newsroom-articles";
import { bodyWithVariation, changeReasonFor, frontMatterWithVariation, type StoryVariationView } from "../lib/story-variations";
import { loadStoryReportingTrail } from "./story-reporting-trail-client";

/**
 * Accepting a variation from outside the Story's editor (the Needs me idea batch): reads the Story's latest version and saves the variation's wording as its
 * next version, with `variationId` in the front matter. The editor does the same with the version it already has open.
 */
export async function saveVariationAsNextVersion(lineageId: string, variation: StoryVariationView, demo = false): Promise<{ id: string; versionNumber: number | null }> {
  const preview = demo || isLocalPreviewEnabled();
  const backend = resolveArticlesBackend(preview);
  const trail = await loadStoryReportingTrail(lineageId, lineageId, preview).catch(() => null);
  const latestId = trail?.versions[0]?.id ?? (preview ? previewVersionIdForLineage(lineageId) : null) ?? lineageId;
  const article = await backend.loadArticle(latestId);
  const result = await backend.actions.saveItemDraft({
    id: article.id, type: article.type, slug: article.slug, section: article.section, aliases: article.aliases, expectedContentHash: article.contentHash,
    frontMatterYaml: frontMatterWithVariation(article.frontMatterYaml ?? "", variation), bodyMarkus: bodyWithVariation(article.bodyMarkus, variation),
    newVersion: true, changeReason: changeReasonFor(variation),
  });
  return { id: result.item.id, versionNumber: result.item.versionNumber };
}
