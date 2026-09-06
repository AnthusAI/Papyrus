import type { EditionLayoutPlan } from "./layout-plan";
import { normalizeEditionLayoutPlan } from "./layout-plan";

export const EMPTY_EDITION_PLACEHOLDER_SLUG = "empty-edition-placeholder";

export type EmptyEditionLayoutPlanInput = {
  placeholderSlug?: string;
  sectionItemSlugs: string[];
  sectionsCtaSlug: string;
  topicItemSlugs: string[];
  topicsCtaSlug: string;
};

export function buildEmptyEditionLayoutPlan({
  placeholderSlug = EMPTY_EDITION_PLACEHOLDER_SLUG,
  sectionItemSlugs,
  sectionsCtaSlug,
  topicItemSlugs,
  topicsCtaSlug,
}: EmptyEditionLayoutPlanInput): EditionLayoutPlan {
  return normalizeEditionLayoutPlan({
    pages: [
      {
        id: "page-1",
        pageNumber: 1,
        presetId: "front.mosaic",
        grid: { columns: { min: 1, preferred: 6, max: 6 } },
        regions: [
          {
            id: "empty-front-page",
            type: "fullPage",
            localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
            blocks: [
              {
                id: "empty-edition-placeholder-front",
                type: "articleFrame",
                presetId: "front.teaser",
                itemId: placeholderSlug,
                flowKey: placeholderSlug,
                startCursor: "beginning",
                role: "primary",
                editorialPriority: "primary",
                size: { shrinkToContent: true },
                typography: { headlineScale: "feature" },
                span: { min: 1, preferred: 6, max: 6 },
                localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
                media: [],
              },
            ],
          },
        ],
      },
      {
        id: "page-2",
        pageNumber: 2,
        presetId: "page.full",
        grid: { columns: { min: 1, preferred: 6, max: 6 } },
        regions: [
          {
            id: "empty-sections-page",
            type: "fullPage",
            size: { shrinkToContent: true },
            localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
            blocks: [
              {
                id: "empty-edition-sections-stack",
                type: "itemStack",
                title: "Sections",
                itemIds: [...sectionItemSlugs, sectionsCtaSlug],
              },
            ],
          },
        ],
      },
      {
        id: "page-3",
        pageNumber: 3,
        presetId: "page.full",
        grid: { columns: { min: 1, preferred: 6, max: 6 } },
        regions: [
          {
            id: "empty-topics-page",
            type: "fullPage",
            size: { shrinkToContent: true },
            localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
            blocks: [
              {
                id: "empty-edition-topics-stack",
                type: "itemStack",
                title: "Topics",
                itemIds: [...topicItemSlugs, topicsCtaSlug],
              },
            ],
          },
        ],
      },
    ],
  }, "EmptyGraphQLEdition.layoutPlan");
}

/** Page-1-only placeholder used on SiteBrand.rendererConfig.layoutPlan. */
export function buildDefaultEmptyEditionLayoutPlan(): EditionLayoutPlan {
  return buildEmptyEditionLayoutPlan({
    sectionItemSlugs: [],
    sectionsCtaSlug: "empty-edition-sections-newsroom",
    topicItemSlugs: [],
    topicsCtaSlug: "empty-edition-topics-newsroom",
  });
}
