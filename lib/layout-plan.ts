import { z } from "zod";
import {
  type PublicationItem,
  getPublicationItemImageAssets,
  getPublicationItemText,
} from "./publication-items";

export const PAGE_PRESETS = [
  "front.mosaic",
  "page.regionStack",
  "page.railMain",
  "page.full",
] as const;

export const REGION_TYPES = [
  "stack",
  "split",
  "railMain",
  "strip",
  "fullPage",
] as const;

export const BLOCK_TYPES = [
  "articleFrame",
  "itemFrame",
  "mediaCluster",
  "itemStack",
  "promoStrip",
  "adBlock",
  "rule",
  "masthead",
] as const;

export const ARTICLE_FRAME_PRESETS = [
  "front.teaser",
  "article.standard",
  "article.mediaInset",
  "article.mediaPrelude",
] as const;

export const MEDIA_CLUSTER_PRESETS = [
  "media.triptych",
  "media.mosaic",
] as const;

export const AD_PRESETS = [
  "ad.fullPage",
  "ad.region",
] as const;

export const RESPONSIVE_PLACEMENT_ANCHORS = [
  "left",
  "right",
  "center",
  "outer",
  "inner",
  "inline",
] as const;

export const RESPONSIVE_VERTICAL_PLACEMENTS = [
  "top",
  "upperThird",
  "middle",
  "lowerThird",
] as const;

export const RESPONSIVE_COLLAPSE_POLICIES = [
  "inline",
  "fullWidth",
  "omit",
] as const;

export const RESPONSIVE_CROP_POLICIES = [
  "preserve",
  "cropAllowed",
] as const;

export const HEADLINE_SCALES = [
  "banner",
  "feature",
  "standard",
  "rail",
  "brief",
] as const;

export const EDITORIAL_PRIORITIES = [
  "primary",
  "secondary",
  "tertiary",
  "supporting",
] as const;

export const FRONT_RESPONSIVE_LAYOUT_ORDERS = [
  "plan",
  "editorialPriority",
] as const;

export type PagePresetId = (typeof PAGE_PRESETS)[number];
export type RegionType = (typeof REGION_TYPES)[number];
export type BlockType = (typeof BLOCK_TYPES)[number];
export type ArticleFramePresetId = (typeof ARTICLE_FRAME_PRESETS)[number];
export type MediaClusterPresetId = (typeof MEDIA_CLUSTER_PRESETS)[number];
export type AdPresetId = (typeof AD_PRESETS)[number];
export type ResponsivePlacementAnchor = (typeof RESPONSIVE_PLACEMENT_ANCHORS)[number];
export type ResponsiveVerticalPlacement = (typeof RESPONSIVE_VERTICAL_PLACEMENTS)[number];
export type ResponsiveCollapsePolicy = (typeof RESPONSIVE_COLLAPSE_POLICIES)[number];
export type ResponsiveCropPolicy = (typeof RESPONSIVE_CROP_POLICIES)[number];
export type HeadlineScaleId = (typeof HEADLINE_SCALES)[number];
export type EditorialPriorityId = (typeof EDITORIAL_PRIORITIES)[number];
export type FrontResponsiveLayoutOrder = (typeof FRONT_RESPONSIVE_LAYOUT_ORDERS)[number];

const ItemIdSchema = z.string().min(1);
const EmValueSchema = z
  .string()
  .regex(/^(?:\d+|\d*\.\d+)em$/, "must be an em value like 1em or 2.5em");

const ChromeTextSlotSchema = z
  .object({
    lineHeight: EmValueSchema.optional(),
    paintHeight: EmValueSchema.optional(),
    marginBefore: EmValueSchema.optional(),
    marginAfter: EmValueSchema.optional(),
    minHeight: EmValueSchema.optional(),
  })
  .strict();

const ArticleFrameChromeSchema = z
  .object({
    label: ChromeTextSlotSchema.optional(),
    headline: ChromeTextSlotSchema.optional(),
    deck: ChromeTextSlotSchema.optional(),
    byline: ChromeTextSlotSchema.optional(),
    caption: ChromeTextSlotSchema.optional(),
    pullQuote: ChromeTextSlotSchema.optional(),
    jumpLine: ChromeTextSlotSchema.optional(),
  })
  .strict();

const ArticleFrameTypographySchema = z
  .object({
    headlineScale: z.enum(HEADLINE_SCALES).optional(),
  })
  .strict();

const SpanPolicySchema = z
  .object({
    min: z.number().int().positive(),
    preferred: z.number().int().positive(),
    max: z.number().int().positive(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.min > value.preferred) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["min"],
        message: "min must be less than or equal to preferred",
      });
    }
    if (value.preferred > value.max) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["preferred"],
        message: "preferred must be less than or equal to max",
      });
    }
  });

const ContentRequirementsSchema = z
  .object({
    minWords: z.number().int().positive().optional(),
    maxWords: z.number().int().positive().optional(),
    minImages: z.number().int().nonnegative().optional(),
    imageRole: z.string().min(1).optional(),
    itemType: z.enum(["article", "brief", "correction", "promo", "ad", "sectionHeader"]).optional(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.minWords !== undefined && value.maxWords !== undefined && value.minWords > value.maxWords) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["minWords"],
        message: "minWords must be less than or equal to maxWords",
      });
    }
  });

const LocalGridSchema = z
  .object({
    columns: SpanPolicySchema.default({ min: 1, preferred: 6, max: 6 }),
  })
  .strict();

const PageGridSchema = z
  .object({
    columns: SpanPolicySchema.default({ min: 1, preferred: 6, max: 6 }),
  })
  .strict();

const RegionSizeSchema = z
  .object({
    ratio: z.number().positive().optional(),
    minHeight: z.number().nonnegative().optional(),
    preferredHeight: z.number().nonnegative().optional(),
    maxHeight: z.number().nonnegative().optional(),
    shrinkToContent: z.boolean().default(false),
  })
  .strict();

const ArticleFrameSizeSchema = z
  .object({
    defaultRows: z.number().int().positive().optional(),
    shrinkToContent: z.boolean().default(false),
  })
  .strict();

const FrontResponsiveSlotSchema = z
  .object({
    blockId: z.string().min(1).optional(),
    editorialPriority: z.enum(EDITORIAL_PRIORITIES).optional(),
    priorityOccurrence: z.number().int().positive().default(1),
    columnStart: z.number().int().positive(),
    columnSpan: z.number().int().positive(),
    rowStart: z.number().int().positive(),
    rowSpan: z.number().int().positive().default(1),
  })
  .strict()
  .superRefine((value, context) => {
    if (!value.blockId && !value.editorialPriority) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["blockId"],
        message: "slot must match by blockId or editorialPriority",
      });
    }
  });

const FrontResponsiveOverflowSchema = z
  .object({
    columnSpan: z.union([z.number().int().positive(), z.literal("full")]).default("full"),
    rowSpan: z.number().int().positive().default(1),
  })
  .strict();

const FrontResponsiveLayoutSchema = z
  .object({
    minColumns: z.number().int().positive(),
    maxColumns: z.number().int().positive(),
    order: z.enum(FRONT_RESPONSIVE_LAYOUT_ORDERS).default("plan"),
    slots: z.array(FrontResponsiveSlotSchema).default([]),
    overflow: FrontResponsiveOverflowSchema.default({}),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.minColumns > value.maxColumns) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["minColumns"],
        message: "minColumns must be less than or equal to maxColumns",
      });
    }
  });

const PlacementSchema = z
  .object({
    anchor: z.enum(RESPONSIVE_PLACEMENT_ANCHORS).default("left"),
    columnStart: z.number().int().positive().optional(),
    span: SpanPolicySchema,
    spanOverrides: z.record(z.string(), z.number().int().positive()).optional(),
    vertical: z.enum(RESPONSIVE_VERTICAL_PLACEMENTS).default("upperThird"),
    collapse: z.enum(RESPONSIVE_COLLAPSE_POLICIES).default("inline"),
    crop: z.enum(RESPONSIVE_CROP_POLICIES).default("preserve"),
    wrapsText: z.boolean().default(true),
  })
  .strict();

const MediaSpecSchema = z
  .object({
    required: z.boolean().default(false),
    assetRole: z.string().min(1).optional(),
    placement: PlacementSchema,
    count: SpanPolicySchema.optional(),
    pattern: z.enum(MEDIA_CLUSTER_PRESETS).optional(),
  })
  .strict();

const PullQuoteSpecSchema = z
  .object({
    required: z.boolean().default(false),
    placements: z.array(PlacementSchema).min(1),
  })
  .strict();

const ArticleFrameCompositionSlotSchema = z
  .object({
    slot: z.enum(["label", "headline", "deck", "byline", "media", "pullQuote"]),
    mediaIndex: z.number().int().nonnegative().optional(),
    placement: PlacementSchema,
  })
  .strict();

const ArticleFrameCompositionSchema = z
  .object({
    title: z.array(ArticleFrameCompositionSlotSchema).default([]),
    lead: z.array(ArticleFrameCompositionSlotSchema).default([]),
  })
  .strict();

const CutPolicySchema = z
  .object({
    bodyDepthRows: z.number().int().positive().optional(),
    maxBodyLines: z.number().int().positive().optional(),
    jumpTargetPage: z.number().int().positive().optional(),
  })
  .strict();

const ArticleFrameBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("articleFrame"),
    presetId: z.enum(ARTICLE_FRAME_PRESETS),
    itemId: ItemIdSchema,
    flowKey: z.string().min(1).optional(),
    startCursor: z.enum(["beginning", "current"]).default("current"),
    role: z.string().min(1).optional(),
    editorialPriority: z.enum(EDITORIAL_PRIORITIES).default("tertiary"),
    localGrid: LocalGridSchema.optional(),
    span: SpanPolicySchema.optional(),
    media: z.array(MediaSpecSchema).default([]),
    pullQuote: PullQuoteSpecSchema.optional(),
    size: ArticleFrameSizeSchema.optional(),
    chrome: ArticleFrameChromeSchema.optional(),
    typography: ArticleFrameTypographySchema.optional(),
    composition: ArticleFrameCompositionSchema.optional(),
    cutPolicy: CutPolicySchema.optional(),
    requires: ContentRequirementsSchema.optional(),
  })
  .strict();

const ItemFrameBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("itemFrame"),
    itemId: ItemIdSchema,
    localGrid: LocalGridSchema.optional(),
    span: SpanPolicySchema.optional(),
    media: z.array(MediaSpecSchema).default([]),
    requires: ContentRequirementsSchema.optional(),
  })
  .strict();

const MediaClusterBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("mediaCluster"),
    itemId: ItemIdSchema,
    presetId: z.enum(MEDIA_CLUSTER_PRESETS),
    assetRole: z.string().min(1).optional(),
    count: SpanPolicySchema.default({ min: 0, preferred: 3, max: 5 }),
    caption: z.string().optional(),
    required: z.boolean().default(false),
  })
  .strict();

const ItemStackBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("itemStack"),
    itemIds: z.array(ItemIdSchema).min(1),
    title: z.string().optional(),
  })
  .strict();

const PromoStripBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("promoStrip"),
    itemIds: z.array(ItemIdSchema).min(1),
  })
  .strict();

const AdBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("adBlock"),
    presetId: z.enum(AD_PRESETS),
    itemId: ItemIdSchema.optional(),
    imageUrl: z.string().url().optional(),
    label: z.string().min(1).optional(),
    required: z.boolean().default(false),
  })
  .strict();

const RuleBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("rule"),
  })
  .strict();

const MastheadBlockSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("masthead"),
  })
  .strict();

const LayoutBlockSchema = z.discriminatedUnion("type", [
  ArticleFrameBlockSchema,
  ItemFrameBlockSchema,
  MediaClusterBlockSchema,
  ItemStackBlockSchema,
  PromoStripBlockSchema,
  AdBlockSchema,
  RuleBlockSchema,
  MastheadBlockSchema,
]);

const LayoutRegionSchema = z
  .object({
    id: z.string().min(1),
    type: z.enum(REGION_TYPES),
    role: z.string().min(1).optional(),
    size: RegionSizeSchema.optional(),
    localGrid: LocalGridSchema.optional(),
    responsiveLayouts: z.array(FrontResponsiveLayoutSchema).optional(),
    blocks: z.array(LayoutBlockSchema).min(1),
  })
  .strict();

const LayoutPageSchema = z
  .object({
    id: z.string().min(1).optional(),
    pageNumber: z.number().int().positive(),
    presetId: z.enum(PAGE_PRESETS),
    grid: PageGridSchema.optional(),
    regions: z.array(LayoutRegionSchema).min(1),
  })
  .strict();

const EditionLayoutPlanSchema = z
  .object({
    pages: z.array(LayoutPageSchema).min(1),
  })
  .strict();

export type ContentRequirements = z.infer<typeof ContentRequirementsSchema>;
export type EmValue = z.infer<typeof EmValueSchema>;
export type ChromeTextSlotSpec = z.infer<typeof ChromeTextSlotSchema>;
export type ArticleFrameChromeSpec = z.infer<typeof ArticleFrameChromeSchema>;
export type ArticleFrameTypographySpec = z.infer<typeof ArticleFrameTypographySchema>;
export type ResponsiveSpanPolicy = z.infer<typeof SpanPolicySchema>;
export type ResponsivePlacementSpec = z.infer<typeof PlacementSchema>;
export type LayoutMediaSpec = z.infer<typeof MediaSpecSchema>;
export type LayoutPullQuoteSpec = z.infer<typeof PullQuoteSpecSchema>;
export type ArticleFrameSizeSpec = z.infer<typeof ArticleFrameSizeSchema>;
export type ArticleFrameCompositionSlotSpec = z.infer<typeof ArticleFrameCompositionSlotSchema>;
export type ArticleFrameCompositionSpec = z.infer<typeof ArticleFrameCompositionSchema>;
export type FrontResponsiveSlotSpec = z.infer<typeof FrontResponsiveSlotSchema>;
export type FrontResponsiveLayoutSpec = z.infer<typeof FrontResponsiveLayoutSchema>;
export type ArticleFrameBlockSpec = z.infer<typeof ArticleFrameBlockSchema>;
export type ItemFrameBlockSpec = z.infer<typeof ItemFrameBlockSchema>;
export type MediaClusterBlockSpec = z.infer<typeof MediaClusterBlockSchema>;
export type ItemStackBlockSpec = z.infer<typeof ItemStackBlockSchema>;
export type PromoStripBlockSpec = z.infer<typeof PromoStripBlockSchema>;
export type AdBlockSpec = z.infer<typeof AdBlockSchema>;
export type LayoutBlockSpec = z.infer<typeof LayoutBlockSchema>;
export type LayoutRegionSpec = z.infer<typeof LayoutRegionSchema>;
export type LayoutPageSpec = z.infer<typeof LayoutPageSchema>;
export type EditionLayoutPlan = z.infer<typeof EditionLayoutPlanSchema>;

export type ArticleCutPolicy = ArticleFrameBlockSpec["cutPolicy"];

export function createDefaultEditionLayoutPlan(
  itemIds: string[],
  cutPoliciesByItemId: Record<string, ArticleCutPolicy> = {},
): EditionLayoutPlan {
  const frontItemIds = getDefaultFrontItemOrder(itemIds);
  const frontBlocks = frontItemIds.map((itemId, index) => ({
    id: `front-${itemId}`,
    type: "articleFrame" as const,
    presetId: "front.teaser" as const,
    itemId,
    flowKey: itemId,
    startCursor: "beginning" as const,
    role: getDefaultFrontRole(index),
    editorialPriority: getDefaultFrontEditorialPriority(index),
    typography: { headlineScale: getDefaultFrontHeadlineScale(index) },
    span: getDefaultFrontSpan(index),
    localGrid: index === 1 ? { columns: { min: 1, preferred: 4, max: 4 } } : undefined,
    media: index === 1
      ? [
          {
            required: true,
            assetRole: "lead",
            placement: {
              anchor: "right",
              span: { min: 1, preferred: 2, max: 2 },
              vertical: "top",
              collapse: "inline",
              crop: "preserve",
              wrapsText: true,
            },
          },
        ]
      : [],
    composition: index === 1
      ? {
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
              placement: {
                columnStart: 1,
                span: { min: 1, preferred: 2, max: 2 },
                vertical: "top",
                collapse: "inline",
                crop: "preserve",
                wrapsText: false,
              },
            },
          ],
          lead: [
            {
              slot: "deck",
              placement: {
                columnStart: 1,
                span: { min: 1, preferred: 2, max: 2 },
                vertical: "top",
                collapse: "inline",
                crop: "preserve",
                wrapsText: true,
              },
            },
            {
              slot: "byline",
              placement: {
                columnStart: 1,
                span: { min: 1, preferred: 2, max: 2 },
                vertical: "top",
                collapse: "inline",
                crop: "preserve",
                wrapsText: true,
              },
            },
            {
              slot: "media",
              mediaIndex: 0,
              placement: {
                anchor: "right",
                span: { min: 1, preferred: 2, max: 2 },
                vertical: "top",
                collapse: "inline",
                crop: "preserve",
                wrapsText: true,
              },
            },
          ],
        }
      : undefined,
    cutPolicy: cutPoliciesByItemId[itemId],
  }));

  const plan: EditionLayoutPlan = normalizeEditionLayoutPlan({
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
            responsiveLayouts: getDefaultFrontResponsiveLayouts(),
            blocks: frontBlocks,
          },
        ],
      },
      {
        id: "page-2",
        pageNumber: 2,
        presetId: "page.regionStack",
        grid: { columns: { min: 1, preferred: 6, max: 6 } },
        regions: [
          {
            id: "harbor-continuation",
            type: "fullPage",
            size: { shrinkToContent: true },
            blocks: [
              {
                id: "agent-procedure-patterns-page-2",
                type: "articleFrame",
                presetId: "article.mediaInset",
                itemId: "agent-procedure-patterns",
                flowKey: "agent-procedure-patterns",
                startCursor: "current",
                role: "primary",
                localGrid: { columns: { min: 2, preferred: 6, max: 6 } },
                media: [
                  {
                    required: true,
                    assetRole: "continuationInset",
                    placement: {
                      anchor: "center",
                      span: { min: 1, preferred: 2, max: 3 },
                      vertical: "upperThird",
                      collapse: "inline",
                      crop: "preserve",
                      wrapsText: true,
                    },
                  },
                ],
                pullQuote: {
                  required: false,
                  placements: [
                    {
                      anchor: "right",
                      span: { min: 1, preferred: 1, max: 2 },
                      vertical: "middle",
                      collapse: "omit",
                      crop: "preserve",
                      wrapsText: true,
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
      {
        id: "page-3",
        pageNumber: 3,
        presetId: "page.regionStack",
        grid: { columns: { min: 1, preferred: 6, max: 6 } },
        regions: [
          {
            id: "schools-reading-lab-tail",
            type: "stack",
            role: "top",
            size: { ratio: 0.5 },
            blocks: [
              {
                id: "schools-reading-lab-page-3",
                type: "articleFrame",
                presetId: "article.mediaInset",
                itemId: "schools-reading-lab",
                flowKey: "schools-reading-lab",
                startCursor: "current",
                role: "top",
                localGrid: { columns: { min: 4, preferred: 6, max: 6 } },
                media: [
                  {
                    required: false,
                    assetRole: "continuationInset",
                    placement: {
                      anchor: "right",
                      span: { min: 1, preferred: 2, max: 2 },
                      vertical: "top",
                      collapse: "inline",
                      crop: "preserve",
                      wrapsText: true,
                    },
                  },
                ],
                pullQuote: {
                  required: false,
                  placements: [
                    {
                      anchor: "left",
                      span: { min: 1, preferred: 1, max: 2 },
                      vertical: "middle",
                      collapse: "omit",
                      crop: "preserve",
                      wrapsText: true,
                    },
                  ],
                },
              },
            ],
          },
          {
            id: "market-hall-tail",
            type: "stack",
            role: "bottom",
            size: { ratio: 0.5 },
            blocks: [
              {
                id: "market-hall-page-3",
                type: "articleFrame",
                presetId: "article.mediaInset",
                itemId: "market-hall",
                flowKey: "market-hall",
                startCursor: "current",
                role: "bottom",
                localGrid: { columns: { min: 2, preferred: 6, max: 6 } },
                media: [
                  {
                    required: false,
                    assetRole: "continuationInset",
                    placement: {
                      anchor: "center",
                      span: { min: 2, preferred: 2, max: 2 },
                      vertical: "top",
                      collapse: "inline",
                      crop: "preserve",
                      wrapsText: true,
                    },
                  },
                ],
                pullQuote: {
                  required: false,
                  placements: [
                    {
                      anchor: "right",
                      span: { min: 1, preferred: 1, max: 2 },
                      vertical: "middle",
                      collapse: "omit",
                      crop: "preserve",
                      wrapsText: true,
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
    ],
  }, "default layoutPlan");

  return plan;
}

function getDefaultFrontResponsiveLayouts(): FrontResponsiveLayoutSpec[] {
  return [
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
      overflow: { columnSpan: 2, rowSpan: 1 },
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

export function normalizeEditionLayoutPlan(value: unknown, label = "Edition.layoutPlan"): EditionLayoutPlan {
  const parsed = parseMaybeJson(value, label);
  const result = EditionLayoutPlanSchema.safeParse(parsed);
  if (!result.success) {
    throw new Error(formatZodError(label, result.error));
  }
  return result.data;
}

export function validateEditionLayoutPlanForItems(
  layoutPlan: EditionLayoutPlan,
  items: PublicationItem[],
  label = "Edition.layoutPlan",
): EditionLayoutPlan {
  const itemsBySlug = new Map(items.map((item) => [item.slug, item]));
  const pageNumbers = new Set(layoutPlan.pages.map((page) => page.pageNumber));
  const seenPageNumbers = new Set<number>();
  const flowStarts = new Map<string, "beginning" | "current">();

  for (const page of layoutPlan.pages) {
    if (seenPageNumbers.has(page.pageNumber)) throw new Error(`${label}.pages contains duplicate pageNumber ${page.pageNumber}`);
    seenPageNumbers.add(page.pageNumber);
    for (const region of page.regions) {
      for (const block of region.blocks) {
        validateBlock(block, itemsBySlug, pageNumbers, flowStarts, `${label}.pages[${page.pageNumber}].regions.${region.id}`);
      }
    }
  }

  validateJumpTargetsHaveContinuationFrames(layoutPlan, label);

  return layoutPlan;
}

function validateJumpTargetsHaveContinuationFrames(layoutPlan: EditionLayoutPlan, label: string): void {
  const continuationFlowKeysByPageNumber = new Map<number, Set<string>>();
  for (const page of layoutPlan.pages) {
    const flowKeys = new Set<string>();
    for (const region of page.regions) {
      for (const block of region.blocks) {
        if (block.type === "articleFrame" && block.startCursor === "current") flowKeys.add(block.flowKey ?? block.itemId);
      }
    }
    continuationFlowKeysByPageNumber.set(page.pageNumber, flowKeys);
  }
  for (const page of layoutPlan.pages) {
    for (const region of page.regions) {
      for (const block of region.blocks) {
        if (block.type !== "articleFrame") continue;
        const jumpTargetPage = block.cutPolicy?.jumpTargetPage;
        if (!jumpTargetPage) continue;
        const flowKey = block.flowKey ?? block.itemId;
        if (!continuationFlowKeysByPageNumber.get(jumpTargetPage)?.has(flowKey)) {
          throw new Error(
            `${label}.pages[${page.pageNumber}].regions.${region.id}.${block.id} advertises page ${jumpTargetPage} but that page has no startCursor "current" frame for flow ${flowKey}`,
          );
        }
      }
    }
  }
}

function validateBlock(
  block: LayoutBlockSpec,
  itemsBySlug: Map<string, PublicationItem>,
  pageNumbers: Set<number>,
  flowStarts: Map<string, "beginning" | "current">,
  label: string,
): void {
  if (block.type === "rule" || block.type === "masthead") return;
  if (block.type === "itemStack" || block.type === "promoStrip") {
    for (const itemId of block.itemIds) requireKnownItem(itemId, itemsBySlug, label);
    return;
  }
  if (block.type === "adBlock") {
    if (block.itemId) requireKnownItem(block.itemId, itemsBySlug, label);
    if (block.required && !block.itemId && !block.imageUrl && !block.label) {
      throw new Error(`${label}.${block.id} requires an ad item, imageUrl, or label`);
    }
    return;
  }

  const item = requireKnownItem(block.itemId, itemsBySlug, label);
  if ("requires" in block) validateItemRequirements(item, block.requires, `${label}.${block.id}.requires`);

  if (block.type === "articleFrame") {
    if (item.type !== "article") throw new Error(`${label}.${block.id} articleFrame requires an article item; ${block.itemId} is ${item.type}`);
    const flowKey = block.flowKey ?? block.itemId;
    if (block.startCursor === "beginning") {
      flowStarts.set(flowKey, "beginning");
    } else if (!flowStarts.has(flowKey)) {
      throw new Error(`${label}.${block.id} starts flow ${flowKey} at current before any beginning block`);
    }
    if (block.cutPolicy?.jumpTargetPage && !pageNumbers.has(block.cutPolicy.jumpTargetPage)) {
      throw new Error(`${label}.${block.id} points to missing jumpTargetPage ${block.cutPolicy.jumpTargetPage}`);
    }
    for (const media of block.media) validateMediaSpec(item, media, `${label}.${block.id}.media`);
    validateArticleFramePlacementGeometry(block, `${label}.${block.id}`);
    if (block.pullQuote?.required && !item.pullQuotes?.[0]) {
      throw new Error(`${label}.${block.id}.pullQuote requires an editorial pull quote`);
    }
  }

  if (block.type === "mediaCluster") {
    const assets = findAssetsByRole(item, block.assetRole);
    if (block.required && assets.length < block.count.min) {
      throw new Error(`${label}.${block.id} requires at least ${block.count.min} media assets`);
    }
  }
}

function validateMediaSpec(item: PublicationItem, media: LayoutMediaSpec, label: string): void {
  const matchingAssets = findAssetsByRole(item, media.assetRole);
  if (media.required && matchingAssets.length === 0) {
    throw new Error(`${label} requires an image asset${media.assetRole ? ` with role ${media.assetRole}` : ""}`);
  }
}

function validateArticleFramePlacementGeometry(block: ArticleFrameBlockSpec, label: string): void {
  const maxColumns = block.localGrid?.columns.max ?? block.span?.max ?? block.span?.preferred ?? 6;
  block.media.forEach((media, index) => validatePlacementColumnStart(media.placement, maxColumns, `${label}.media[${index}].placement`));
  block.pullQuote?.placements.forEach((placement, index) => (
    validatePlacementColumnStart(placement, maxColumns, `${label}.pullQuote.placements[${index}]`)
  ));
  block.composition?.title.forEach((slot, index) => (
    validatePlacementColumnStart(slot.placement, maxColumns, `${label}.composition.title[${index}].placement`)
  ));
  block.composition?.lead.forEach((slot, index) => (
    validatePlacementColumnStart(slot.placement, maxColumns, `${label}.composition.lead[${index}].placement`)
  ));
}

function validatePlacementColumnStart(placement: ResponsivePlacementSpec, maxColumns: number, label: string): void {
  if (!placement.columnStart) return;
  const lastColumn = placement.columnStart + placement.span.max - 1;
  if (lastColumn > maxColumns) {
    throw new Error(`${label} columnStart ${placement.columnStart} with max span ${placement.span.max} exceeds ${maxColumns} local columns`);
  }
}

function validateItemRequirements(item: PublicationItem, requirements: ContentRequirements | undefined, label: string): void {
  if (!requirements) return;
  if (requirements.itemType && item.type !== requirements.itemType) {
    throw new Error(`${label} requires item type ${requirements.itemType}; ${item.slug} is ${item.type}`);
  }
  const wordCount = getPublicationItemText(item).split(/\s+/).filter(Boolean).length;
  const assets = getPublicationItemImageAssets(item);
  if (requirements.minWords !== undefined && wordCount < requirements.minWords) {
    throw new Error(`${label} requires at least ${requirements.minWords} words; ${item.slug} has ${wordCount}`);
  }
  if (requirements.maxWords !== undefined && wordCount > requirements.maxWords) {
    throw new Error(`${label} allows at most ${requirements.maxWords} words; ${item.slug} has ${wordCount}`);
  }
  if (requirements.minImages !== undefined && assets.length < requirements.minImages) {
    throw new Error(`${label} requires at least ${requirements.minImages} images; ${item.slug} has ${assets.length}`);
  }
  if (requirements.imageRole && findAssetsByRole(item, requirements.imageRole).length === 0) {
    throw new Error(`${label} requires an image with role ${requirements.imageRole}`);
  }
}

function findAssetsByRole(item: PublicationItem, role: string | undefined) {
  const assets = getPublicationItemImageAssets(item);
  if (!role) return assets;
  return assets.filter((asset) => asset.roles?.some((assetRole) => assetRole === role));
}

function requireKnownItem(itemId: string, itemsBySlug: Map<string, PublicationItem>, label: string): PublicationItem {
  const item = itemsBySlug.get(itemId);
  if (!item) throw new Error(`${label} references missing item ${itemId}`);
  return item;
}

function getDefaultFrontSpan(index: number): ResponsiveSpanPolicy {
  const preferred = [1, 4, 1, 2, 2, 2][index] ?? 1;
  return { min: 1, preferred, max: preferred };
}

function getDefaultFrontRole(index: number): string {
  if (index === 1) return "feature";
  if (index === 0 || index === 2) return "rail";
  return "standard";
}

function getDefaultFrontHeadlineScale(index: number): HeadlineScaleId {
  if (index === 1) return "feature";
  if (index === 0 || index === 2) return "rail";
  return "standard";
}

function getDefaultFrontEditorialPriority(index: number): EditorialPriorityId {
  if (index === 1) return "primary";
  if (index === 0 || index === 2) return "secondary";
  return "tertiary";
}

function getDefaultFrontItemOrder(itemIds: string[]): string[] {
  if (itemIds.length < 3) return itemIds;
  return [itemIds[1], itemIds[0], itemIds[2], ...itemIds.slice(3)];
}

function parseMaybeJson(value: unknown, label: string): unknown {
  if (typeof value !== "string") {
    if (value === undefined || value === null) throw new Error(`${label} is required`);
    return value;
  }
  if (!value.trim()) throw new Error(`${label} is required`);
  try {
    return JSON.parse(value);
  } catch (error) {
    throw new Error(`${label} must be valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function formatZodError(label: string, error: z.ZodError): string {
  return `${label} is invalid:\n${error.issues
    .map((issue) => `- ${[label, ...issue.path].join(".")}: ${issue.message}`)
    .join("\n")}`;
}
