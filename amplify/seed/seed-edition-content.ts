import type { Article } from "../../lib/articles";
import { getSeedEditionContentSource, type SeedHouseAd } from "./seed-profile";

const seedContentSource = getSeedEditionContentSource();
const seedContent = seedContentSource.content;

export const seedEditionArticles: Article[] = seedContent.articles;

export type SeedEditionConfig = {
  id: string;
  slug: string;
  title: string;
  description: string;
  publishDate: string;
  publishedAt: string;
  metadata: Record<string, unknown>;
  articleOrder: string[];
  layoutPlan: unknown;
};

export function getSeedEditionConfig(): SeedEditionConfig {
  const publishDate = seedContent.publishDate;
  const itemIds = seedEditionArticles.map((article) => article.slug);
  return {
    id: seedContent.id,
    slug: seedContent.slug,
    title: seedContent.title,
    description: seedContent.description,
    publishDate,
    publishedAt: `${publishDate}T12:00:00.000Z`,
    metadata: {
      source: "fixture-seed",
      suppressNewsDeskAppendix: seedContent.suppressNewsDeskAppendix === true,
      ...(seedContent.video ? { editionVideo: seedContent.video } : {}),
    },
    articleOrder: itemIds,
    layoutPlan: applySeedHouseAds(createSeedEditionLayoutPlan(seedEditionArticles), seedContent.houseAds),
  };
}

export function getSeedEditionProfileInfo() {
  return {
    id: seedContentSource.profileId,
    sourcePath: seedContentSource.sourcePath,
  };
}

function applySeedHouseAds(layoutPlan: ReturnType<typeof createSeedEditionLayoutPlan>, houseAds: SeedHouseAd[] | undefined) {
  if (!houseAds?.length) return layoutPlan;
  for (const ad of houseAds) {
    const page = layoutPlan.pages.find((entry) => entry.pageNumber === ad.pageNumber);
    const region = page?.regions?.[0];
    if (!region) continue;
    (region.blocks as Array<Record<string, unknown>>).push({
      id: ad.id,
      type: "adBlock",
      presetId: ad.presetId ?? "ad.region",
      required: false,
      label: ad.label,
    });
  }
  return layoutPlan;
}

function createSeedEditionLayoutPlan(articles: Article[]) {
  const itemIds = articles.map((article) => article.slug);
  const imageByItemId = new Map(articles.map((article) => [article.slug, hasSeedImage(article)]));
  const frontItemIds = itemIds.slice(0, Math.min(itemIds.length, 4));
  const followOnBlocks = [
    ...frontItemIds.map((itemId) =>
      createSeedContinuationBlock(itemId, 0, imageByItemId.get(itemId) ? getSeedMediaPlacement(0) : undefined),
    ),
    ...itemIds.slice(frontItemIds.length).map((itemId, index) =>
      createSeedPageArticleBlock(
        itemId,
        0,
        imageByItemId.get(itemId) ? getSeedMediaPlacement(index + frontItemIds.length) : undefined,
      ),
    ),
  ];
  return {
    pages: [
      {
        id: "page-1",
        pageNumber: 1,
        presetId: "front.mosaic",
        grid: { columns: { min: 1, preferred: 6, max: 6 } },
        regions: [
          {
            id: "front-page-news",
            type: "fullPage",
            localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
            responsiveLayouts: getSeedFrontResponsiveLayouts(),
            blocks: frontItemIds.map((itemId, index) => createSeedFrontBlock(itemId, index, imageByItemId.get(itemId) === true)),
          },
        ],
      },
      ...createSeedFollowOnPages(followOnBlocks),
    ],
  };
}

function hasSeedImage(article: Article) {
  return Boolean(article.assets?.some((asset) => asset.type === "image" && asset.src) || article.image?.src);
}

function createSeedFrontBlock(itemId: string, index: number, hasImage: boolean) {
  const preferredSpan = [1, 4, 1, 2, 2, 2][index] ?? 1;
  const isFeature = index === 1;
  return {
    id: `front-${itemId}`,
    type: "articleFrame",
    presetId: "front.teaser",
    itemId,
    flowKey: itemId,
    startCursor: "beginning",
    role: isFeature ? "feature" : index === 0 || index === 2 ? "rail" : "standard",
    editorialPriority: isFeature ? "primary" : index === 0 || index === 2 ? "secondary" : "tertiary",
    typography: { headlineScale: isFeature ? "feature" : "standard" },
    span: { min: 1, preferred: preferredSpan, max: preferredSpan },
    localGrid: isFeature ? { columns: { min: 1, preferred: 4, max: 4 } } : undefined,
    media: isFeature && hasImage
      ? [
          {
            required: true,
            assetRole: "lead",
            placement: {
              anchor: "right",
              span: { min: 1, preferred: 1, max: 1 },
              vertical: "top",
              collapse: "inline",
              crop: "preserve",
              wrapsText: true,
            },
          },
        ]
      : [],
    composition: isFeature ? createSeedFeatureComposition(hasImage) : undefined,
    cutPolicy: getSeedCutPolicy(itemId, index),
  };
}

function createSeedFeatureComposition(hasImage: boolean) {
  const titlePlacement = {
    columnStart: 1,
    span: { min: 1, preferred: 3, max: 3 },
    spanOverrides: { "3": 2 },
    vertical: "top",
    collapse: "inline",
    crop: "preserve",
    wrapsText: false,
  };
  const leadPlacement = { ...titlePlacement, wrapsText: true };
  return {
    title: [
      {
        slot: "label",
        placement: {
          columnStart: 1,
          span: { min: 1, preferred: 2, max: 2 },
          vertical: "top",
          collapse: "inline",
          crop: "preserve",
          wrapsText: false,
        },
      },
      {
        slot: "headline",
        placement: titlePlacement,
      },
    ],
    lead: [
      {
        slot: "deck",
        placement: leadPlacement,
      },
      {
        slot: "byline",
        placement: leadPlacement,
      },
      ...(hasImage
        ? [
            {
              slot: "media",
              mediaIndex: 0,
              placement: {
                anchor: "right",
                span: { min: 1, preferred: 1, max: 1 },
                vertical: "top",
                collapse: "inline",
                crop: "preserve",
                wrapsText: true,
              },
            },
          ]
        : []),
    ],
  };
}

type SeedLayoutArticleBlock = ReturnType<typeof createSeedPageArticleBlock> | ReturnType<typeof createSeedContinuationBlock>;

function createSeedFollowOnPages(blocks: SeedLayoutArticleBlock[]) {
  return chunk(blocks, 2).map((pageBlocks, pageIndex) => {
    const pageNumber = pageIndex + 2;
    return {
      id: `page-${pageNumber}`,
      pageNumber,
      presetId: "page.regionStack",
      grid: { columns: { min: 1, preferred: 6, max: 6 } },
      regions: pageBlocks.map((block, blockIndex) => ({
        id: `${block.itemId}-page-${pageNumber}-${blockIndex === 0 ? "top" : "bottom"}`,
        type: "stack",
        role: blockIndex === 0 ? "top" : "bottom",
        size: { ratio: pageBlocks.length === 1 ? 1 : 0.5 },
        blocks: [
          {
            ...block,
            id: `${block.id}-page-${pageNumber}`,
            ...(block.startCursor === "current" ? {} : { startCursor: "beginning" }),
          },
        ],
      })),
    };
  });
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function getSeedFrontResponsiveLayouts() {
  return [
    {
      minColumns: 6,
      maxColumns: 6,
      order: "editorialPriority",
      slots: [
        {
          editorialPriority: "secondary",
          priorityOccurrence: 1,
          columnStart: 1,
          columnSpan: 1,
          rowStart: 1,
          rowSpan: 1,
        },
        {
          editorialPriority: "primary",
          priorityOccurrence: 1,
          columnStart: 2,
          columnSpan: 4,
          rowStart: 1,
          rowSpan: 1,
        },
        {
          editorialPriority: "secondary",
          priorityOccurrence: 2,
          columnStart: 6,
          columnSpan: 1,
          rowStart: 1,
          rowSpan: 1,
        },
      ],
      overflow: { columnSpan: "full", rowSpan: 1 },
    },
    {
      minColumns: 5,
      maxColumns: 5,
      order: "editorialPriority",
      slots: [
        {
          editorialPriority: "secondary",
          priorityOccurrence: 1,
          columnStart: 1,
          columnSpan: 1,
          rowStart: 1,
          rowSpan: 1,
        },
        {
          editorialPriority: "primary",
          priorityOccurrence: 1,
          columnStart: 2,
          columnSpan: 3,
          rowStart: 1,
          rowSpan: 1,
        },
        {
          editorialPriority: "secondary",
          priorityOccurrence: 2,
          columnStart: 5,
          columnSpan: 1,
          rowStart: 1,
          rowSpan: 1,
        },
      ],
      overflow: { columnSpan: "full", rowSpan: 1 },
    },
    {
      minColumns: 4,
      maxColumns: 4,
      order: "editorialPriority",
      slots: [
        {
          editorialPriority: "primary",
          priorityOccurrence: 1,
          columnStart: 1,
          columnSpan: 4,
          rowStart: 1,
          rowSpan: 1,
        },
        {
          editorialPriority: "secondary",
          priorityOccurrence: 1,
          columnStart: 1,
          columnSpan: 2,
          rowStart: 2,
          rowSpan: 1,
        },
        {
          editorialPriority: "secondary",
          priorityOccurrence: 2,
          columnStart: 3,
          columnSpan: 2,
          rowStart: 2,
          rowSpan: 1,
        },
      ],
      overflow: { columnSpan: "full", rowSpan: 1 },
    },
    {
      minColumns: 1,
      maxColumns: 3,
      order: "editorialPriority",
      slots: [],
      overflow: { columnSpan: "full", rowSpan: 1 },
    },
  ];
}

function createSeedPageArticleBlock(
  itemId: string,
  pageNumber: number,
  media?: {
    required: boolean;
    anchor: string;
    span: { min: number; preferred: number; max: number };
    vertical: string;
  },
) {
  return {
    id: `${itemId}-page-${pageNumber}-lead`,
    type: "articleFrame",
    presetId: "article.mediaInset",
    itemId,
    flowKey: itemId,
    startCursor: "beginning",
    role: "primary",
    localGrid: { columns: { min: 2, preferred: 6, max: 6 } },
    media: media
      ? [
          {
            required: media.required,
            assetRole: "lead",
            placement: {
              anchor: media.anchor,
              span: media.span,
              vertical: media.vertical,
              collapse: "inline",
              crop: "preserve",
              wrapsText: true,
            },
          },
        ]
      : [],
  };
}

function createSeedContinuationBlock(
  itemId: string,
  pageNumber: number,
  media?: {
    required: boolean;
    anchor: string;
    span: { min: number; preferred: number; max: number };
    vertical: string;
  },
) {
  return {
    id: `${itemId}-page-${pageNumber}`,
    type: "articleFrame",
    presetId: "article.mediaInset",
    itemId,
    flowKey: itemId,
    startCursor: "current",
    role: "primary",
    localGrid: { columns: { min: 2, preferred: 6, max: 6 } },
    media: media
      ? [
          {
            required: media.required,
            assetRole: "continuationInset",
            placement: {
              anchor: media.anchor,
              span: media.span,
              vertical: media.vertical,
              collapse: "inline",
              crop: "preserve",
              wrapsText: true,
            },
          },
        ]
      : [],
    pullQuote: media
      ? {
          required: false,
          placements: [
            {
              anchor: media.anchor === "left" ? "right" : "left",
              span: { min: 1, preferred: 1, max: 2 },
              vertical: "middle",
              collapse: "omit",
              crop: "preserve",
              wrapsText: true,
            },
          ],
        }
      : undefined,
  };
}

function getSeedMediaPlacement(index: number) {
  return index % 2 === 0
    ? {
        required: false,
        anchor: "right",
        span: { min: 1, preferred: 2, max: 2 },
        vertical: "top",
      }
    : {
        required: false,
        anchor: "center",
        span: { min: 1, preferred: 2, max: 3 },
        vertical: "upperThird",
      };
}

function getSeedCutPolicy(_itemId: string, index: number) {
  if (index > 3) return undefined;
  return {
    bodyDepthRows: index === 3 ? 8 : 14,
    jumpTargetPage: Math.floor(index / 2) + 2,
  };
}
