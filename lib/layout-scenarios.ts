import { type Article, type ArticleVideoAsset, articles, editionDate } from "./articles";
import type { EditionContent, NewsDeskAppendix } from "./content-types";
import { createEditionSectionPlan } from "./edition-sections";
import { createDefaultEditionLayoutPlan, type EditionLayoutPlan } from "./layout-plan";
import { articleToPublicationItem, cloneArticle } from "./publication-items";
import { SITE_BRAND } from "./site-brand";
import threatIntelligenceSeedContent from "../publications/threat_intelligence/seed/seed-edition-content.json";

export type LayoutScenario = EditionContent & {
  source: "scenario";
  scenarioId: string;
};

export const DEFAULT_LAYOUT_SCENARIO_ID = "current-edition";

type RawLayoutScenario = Omit<LayoutScenario, "sections"> & {
  sections?: LayoutScenario["sections"];
};

const defaultScenarioSeed = getDefaultScenarioSeed();

const rawLayoutScenarios: RawLayoutScenario[] = [
  {
    id: DEFAULT_LAYOUT_SCENARIO_ID,
    source: "scenario",
    title: defaultScenarioSeed.title,
    editionDate: defaultScenarioSeed.editionDate,
    scenarioId: DEFAULT_LAYOUT_SCENARIO_ID,
    description: defaultScenarioSeed.description,
    layoutPlan: createDefaultEditionLayoutPlan(defaultScenarioSeed.articles.map((article) => article.slug)),
    items: cloneArticles(defaultScenarioSeed.articles).map(articleToPublicationItem),
    suppressNewsDeskAppendix: defaultScenarioSeed.suppressNewsDeskAppendix,
    editionVideo: defaultScenarioSeed.editionVideo,
    newsDeskAppendix: defaultScenarioSeed.newsDeskAppendix,
  },
  {
    id: "blank-edition-title",
    source: "scenario",
    title: "   ",
    editionDate,
    scenarioId: "blank-edition-title",
    description: "A fixture edition with a blank title used to verify masthead fallback labeling.",
    layoutPlan: createDefaultEditionLayoutPlan(articles.map((article) => article.slug)),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
  {
    id: "shared-blank-column-pressure",
    source: "scenario",
    title: "Shared Continuation Blank Column Pressure",
    editionDate,
    scenarioId: "shared-blank-column-pressure",
    description:
      "Shorter shared continuation tails with images and pull quotes, used to prove that empty columns are repaired with solved furniture.",
    layoutPlan: createDefaultEditionLayoutPlan(articles.map((article) => article.slug)),
    items: createSharedBlankColumnPressureArticles().map(articleToPublicationItem),
  },
  {
    id: "shared-continuation-no-pull-quotes",
    source: "scenario",
    title: "Shared Continuation Without Pull Quotes",
    editionDate,
    scenarioId: "shared-continuation-no-pull-quotes",
    description:
      "The shared continuation page with editorial pull quotes removed, used to prove pull quotes are optional display furniture.",
    layoutPlan: createDefaultEditionLayoutPlan(articles.map((article) => article.slug)),
    items: createNoPullQuoteArticles().map(articleToPublicationItem),
  },
  {
    id: "front-chrome-compact",
    source: "scenario",
    title: "Front Chrome Compact Typography",
    editionDate,
    scenarioId: "front-chrome-compact",
    description:
      "Compact headline and deck line heights prove that em-authored chrome reserves enough paint space to prevent overlap.",
    layoutPlan: createCompactChromeLayoutPlan(),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
  {
    id: "front-body-depth-rows",
    source: "scenario",
    title: "Front Body Depth Rows",
    editionDate,
    scenarioId: "front-body-depth-rows",
    description:
      "Per-column front teaser depth should keep the lead trio aligned while still continuing onto later pages.",
    layoutPlan: createFrontBodyDepthLayoutPlan(),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
  {
    id: "furniture-sufficiency-pressure",
    source: "scenario",
    title: "Furniture Sufficiency Pressure",
    editionDate,
    scenarioId: "furniture-sufficiency-pressure",
    description:
      "Oversized image and pull-quote packages prove that the solver rejects furniture that leaves too little readable copy.",
    layoutPlan: createFurnitureSufficiencyLayoutPlan(),
    items: createFurnitureSufficiencyArticles().map(articleToPublicationItem),
  },
  {
    id: "long-image-caption",
    source: "scenario",
    title: "Long Image Caption",
    editionDate,
    scenarioId: "long-image-caption",
    description:
      "A continuation image with a long caption proves image furniture reserves enough rhythm rows for complete caption text.",
    layoutPlan: createDefaultEditionLayoutPlan(articles.map((article) => article.slug)),
    items: createLongImageCaptionArticles().map(articleToPublicationItem),
  },
  {
    id: "themed-ink-study",
    source: "scenario",
    title: "Themed Ink Study",
    editionDate,
    scenarioId: "themed-ink-study",
    description: "A raster fixture verifies dark-mode image variant switching in solved newspaper image furniture.",
    layoutPlan: createDefaultEditionLayoutPlan(articles.map((article) => article.slug)),
    items: createThemedInkStudyArticles().map(articleToPublicationItem),
  },
  {
    id: "height-policy-fill-default",
    source: "scenario",
    title: "Height Policy Fill Default",
    editionDate,
    scenarioId: "height-policy-fill-default",
    description:
      "A page-two continuation without shrinkToContent proves stacked regions still preserve their allocated fill height by default.",
    layoutPlan: createHeightPolicyLayoutPlan({}),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
  {
    id: "height-policy-default-rows",
    source: "scenario",
    title: "Height Policy Default Rows",
    editionDate,
    scenarioId: "height-policy-default-rows",
    description:
      "A page-two continuation with block defaultRows proves an article frame can hold an editorial row target.",
    layoutPlan: createHeightPolicyLayoutPlan({ regionShrinkToContent: true, defaultRows: 64 }),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
  {
    id: "height-policy-default-rows-grow",
    source: "scenario",
    title: "Height Policy Default Rows Grow",
    editionDate,
    scenarioId: "height-policy-default-rows-grow",
    description:
      "A short article-frame row target proves exhaustive continuation text can grow beyond defaultRows.",
    layoutPlan: createHeightPolicyLayoutPlan({ regionShrinkToContent: true, defaultRows: 12 }),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
  {
    id: "height-policy-default-rows-shrink",
    source: "scenario",
    title: "Height Policy Default Rows Shrink",
    editionDate,
    scenarioId: "height-policy-default-rows-shrink",
    description:
      "A shrinkable article-frame row target proves defaultRows can be released when content solves shorter.",
    layoutPlan: createHeightPolicyLayoutPlan({ regionShrinkToContent: true, defaultRows: 64, blockShrinkToContent: true }),
    items: cloneArticles(articles).map(articleToPublicationItem),
  },
];

export const layoutScenarios: LayoutScenario[] = rawLayoutScenarios.map((scenario) => ({
  ...scenario,
  sections: scenario.sections ?? createEditionSectionPlan(scenario.items),
}));

export function getLayoutScenario(id: string | null | undefined): LayoutScenario {
  return layoutScenarios.find((scenario) => scenario.id === id) ?? layoutScenarios[0];
}

function getDefaultScenarioSeed(): {
  title: string;
  editionDate: string;
  description: string;
  articles: Article[];
  suppressNewsDeskAppendix?: boolean;
  editionVideo?: ArticleVideoAsset;
  newsDeskAppendix?: NewsDeskAppendix | null;
} {
  if (SITE_BRAND.id !== "threat-intelligence") {
    return {
      title: "Current Edition",
      editionDate,
      description: "The default Papyrus fixture edition.",
      articles,
      newsDeskAppendix: createDemoNewsDeskAppendix(),
    };
  }

  return {
    title: threatIntelligenceSeedContent.title,
    editionDate: threatIntelligenceSeedContent.publishDate,
    description: threatIntelligenceSeedContent.description,
    articles: threatIntelligenceSeedContent.articles as Article[],
    suppressNewsDeskAppendix: threatIntelligenceSeedContent.suppressNewsDeskAppendix === true,
    editionVideo: threatIntelligenceSeedContent.video as ArticleVideoAsset | undefined,
    newsDeskAppendix: null,
  };
}

function createSharedBlankColumnPressureArticles(): Article[] {
  return cloneArticles(articles).map((article) => {
    if (article.slug === "schools-reading-lab") {
      return {
        ...article,
        body: [
          article.body[0],
          article.body[1],
          article.body[2],
          article.body[3],
          "The test edition keeps this continuation deliberately tight. It should still spend empty column space with a solved image or pull quote instead of leaving a bare newspaper column.",
        ],
      };
    }

    if (article.slug === "market-hall") {
      return {
        ...article,
        body: [
          article.body[0],
          article.body[1],
          article.body[2],
          "Editors marked this tail as short on purpose. The layout should react by choosing furniture that covers otherwise blank column space without overlapping live copy.",
        ],
      };
    }

    return article;
  });
}

function createNoPullQuoteArticles(): Article[] {
  return cloneArticles(articles).map((article) => {
    if (article.slug === "agent-procedure-patterns" || article.slug === "schools-reading-lab" || article.slug === "market-hall") {
      return {
        ...article,
        pullQuotes: [],
      };
    }

    return article;
  });
}

function createFurnitureSufficiencyArticles(): Article[] {
  return cloneArticles(articles).map((article) => {
    if (article.slug === "schools-reading-lab") {
      if (!article.image) return article;
      return {
        ...article,
        pullQuotes: [],
        image: {
          ...article.image,
          layout: {
            ...article.image.layout,
            minHeight: 120,
            preferredHeight: 900,
            maxHeight: 900,
            aspectRatio: 0.2,
            crop: "contain",
            wrapsText: true,
          },
        },
        body: [
          article.body[0],
          article.body[1],
          "This pressure edition leaves only a compact continuation tail, so an oversized photo package must yield to readable copy.",
        ],
      };
    }

    if (article.slug === "market-hall") {
      return {
        ...article,
        pullQuotes: [
          "The economics depend on sharing, but a display quote that consumes a wide block of columns should not be admitted when it leaves only a few rows of live article copy around it. If the quote keeps expanding across the continuation, the solver should treat that furniture as editorially too expensive for this compact tail.",
        ],
        body: [
          article.body[0],
          article.body[1],
          "The hall still opens before dawn, but the continuation in this scenario is deliberately compact so the solver has to prefer readable copy over oversized furniture.",
        ],
      };
    }

    return article;
  });
}

function createThemedInkStudyArticles(): Article[] {
  return cloneArticles(articles).map((article) => {
    if (article.slug !== "agent-procedure-patterns") return article;
    return {
      ...article,
      image: {
        ...article.image,
        src: "/seed-art/theme-ink-study-light.png",
        themeVariants: {
          dark: {
            src: "/seed-art/theme-ink-study-dark.png",
          },
        },
        alt: "An abstract newspaper study with theme-specific light and dark rendering",
        credit: "Papyrus seed art",
        caption: "Theme-aware raster image fixture.",
        layout: {
          minHeight: 120,
          preferredHeight: 220,
          maxHeight: 420,
          aspectRatio: 1.5009,
          crop: "contain",
          wrapsText: true,
        },
      },
      assets: [
        {
          id: `${article.slug}-primary-image`,
          type: "image",
          src: "/seed-art/theme-ink-study-light.png",
          themeVariants: {
            dark: {
              src: "/seed-art/theme-ink-study-dark.png",
            },
          },
          alt: "An abstract newspaper study with theme-specific light and dark rendering",
          caption: "Theme-aware raster image fixture.",
          credit: "Papyrus seed art",
          roles: ["lead", "continuation", "continuationInset"],
          layout: {
            minHeight: 120,
            preferredHeight: 220,
            maxHeight: 420,
            aspectRatio: 1.5009,
            crop: "contain",
            wrapsText: true,
          },
        },
      ],
    };
  });
}

function createLongImageCaptionArticles(): Article[] {
  return cloneArticles(articles).map((article) => {
    if (article.slug !== "market-hall") return article;
    if (!article.image) return article;
    return {
      ...article,
      image: {
        ...article.image,
        caption:
          "The renovated market hall combines prep kitchens, storefront counters, shared cold storage, and a public retail counter where small producers can test packaging and pricing before committing to wholesale runs.",
      },
    };
  });
}

function createHeightPolicyLayoutPlan({
  regionShrinkToContent,
  defaultRows,
  blockShrinkToContent = false,
}: {
  regionShrinkToContent?: boolean;
  defaultRows?: number;
  blockShrinkToContent?: boolean;
}): EditionLayoutPlan {
  const plan = cloneLayoutPlan(createDefaultEditionLayoutPlan(articles.map((article) => article.slug)));
  const region = findPlanRegion(plan, "harbor-continuation");
  if (region) {
    if (regionShrinkToContent === undefined) {
      delete region.size;
    } else {
      region.size = { ...(region.size ?? {}), shrinkToContent: regionShrinkToContent };
    }
  }

  const block = findPlanBlock(plan, "agent-procedure-patterns-page-2");
  if (block?.type === "articleFrame" && defaultRows !== undefined) {
    block.size = {
      defaultRows,
      shrinkToContent: blockShrinkToContent,
    };
  }

  return plan;
}

function createDemoNewsDeskAppendix(): NewsDeskAppendix {
  const categorySetId = "category-set-demo-canonical";
  return {
    categorySetId,
    corpusId: "category-corpus-demo-canonical",
    displayName: "Canonical Category Register",
    description: "Accepted category tree for the fixture edition.",
    generatedAt: `${editionDate}T12:00:00.000Z`,
    nodes: [
      {
        id: "category-node-foundation-model-scaling",
        categorySetId,
        categoryKey: "category.foundation-model-scaling",
        parentCategoryKey: null,
        displayName: "Foundation Model Scaling",
        subtitle: "Capability curves, benchmark saturation, and training-compute effects",
        description: "Research on model size, data mixtures, compute budgets, and emergent benchmark behavior.",
        status: "accepted",
        seedItemIds: ["research-001", "research-002"],
        holdoutItemIds: ["research-003"],
        rank: 1,
        depth: 0,
      },
      {
        id: "category-node-agent-memory",
        categorySetId,
        categoryKey: "category.agent-memory",
        parentCategoryKey: "category.foundation-model-scaling",
        displayName: "Agent Memory",
        subtitle: "Retrieval, persistence, and working context for autonomous systems",
        description: "Subtopic covering memory stores, retrieval policies, and long-horizon agent state.",
        status: "accepted",
        seedItemIds: ["research-001"],
        holdoutItemIds: [],
        rank: 1,
        depth: 1,
      },
      {
        id: "category-node-benchmark-saturation",
        categorySetId,
        categoryKey: "category.benchmark-saturation",
        parentCategoryKey: "category.foundation-model-scaling",
        displayName: "Benchmark Saturation",
        subtitle: "When evaluation sets stop separating model capability",
        description: "Subtopic covering benchmark exhaustion, contamination, and evaluation drift.",
        status: "accepted",
        seedItemIds: ["research-002"],
        holdoutItemIds: [],
        rank: 2,
        depth: 1,
      },
      {
        id: "category-node-symbolic-connectionist-history",
        categorySetId,
        categoryKey: "category.symbolic-connectionist-history",
        parentCategoryKey: null,
        displayName: "Symbolic And Connectionist History",
        subtitle: "Shifts between rules, neural nets, and hybrid AI programs",
        description: "Historical coverage of symbolic AI, neural network winters, and later hybrid systems.",
        status: "accepted",
        seedItemIds: ["history-001"],
        holdoutItemIds: ["history-002"],
        rank: 2,
        depth: 0,
      },
    ],
  };
}

function cloneArticles(source: Article[]): Article[] {
  return source.map(cloneArticle);
}

function createCompactChromeLayoutPlan(): EditionLayoutPlan {
  const plan = cloneLayoutPlan(createDefaultEditionLayoutPlan(articles.map((article) => article.slug)));
  const frontPage = plan.pages.find((page) => page.pageNumber === 1);
  const frontBlocks = frontPage?.regions.flatMap((region) => region.blocks) ?? [];
  for (const block of frontBlocks) {
    if (block.type !== "articleFrame") continue;
    block.chrome = {
      headline: {
        lineHeight: "0.72em",
        paintHeight: "1.14em",
        marginAfter: "0.32em",
      },
      deck: {
        lineHeight: "0.9em",
        paintHeight: "1.12em",
        minHeight: "2.8em",
      },
      byline: {
        lineHeight: "0.95em",
        paintHeight: "1.1em",
      },
    };
  }
  return plan;
}

function createFrontBodyDepthLayoutPlan(): EditionLayoutPlan {
  const plan = cloneLayoutPlan(createDefaultEditionLayoutPlan(articles.map((article) => article.slug)));
  for (const blockId of ["front-agent-procedure-patterns", "front-schools-reading-lab", "front-market-hall"]) {
    const block = findPlanBlock(plan, blockId);
    if (block?.type !== "articleFrame") continue;
    block.cutPolicy = {
      bodyDepthRows: 14,
      jumpTargetPage: block.cutPolicy?.jumpTargetPage ?? (blockId === "front-agent-procedure-patterns" ? 2 : 3),
    };
  }
  return plan;
}

function createFurnitureSufficiencyLayoutPlan(): EditionLayoutPlan {
  const plan = cloneLayoutPlan(createDefaultEditionLayoutPlan(articles.map((article) => article.slug)));
  const frontSchoolsBlock = findPlanBlock(plan, "front-schools-reading-lab");
  if (frontSchoolsBlock?.type === "articleFrame") {
    frontSchoolsBlock.cutPolicy = { maxBodyLines: 4, jumpTargetPage: 3 };
  }

  const frontMarketBlock = findPlanBlock(plan, "front-market-hall");
  if (frontMarketBlock?.type === "articleFrame") {
    frontMarketBlock.cutPolicy = { maxBodyLines: 4, jumpTargetPage: 3 };
  }

  const schoolsBlock = findPlanBlock(plan, "schools-reading-lab-page-3");
  if (schoolsBlock?.type === "articleFrame") {
    schoolsBlock.localGrid = { columns: { min: 2, preferred: 4, max: 4 } };
    schoolsBlock.media[0].placement.crop = "cropAllowed";
    schoolsBlock.media[0].placement.anchor = "center";
    schoolsBlock.media[0].placement.span = { min: 4, preferred: 4, max: 4 };
  }

  const marketBlock = findPlanBlock(plan, "market-hall-page-3");
  if (marketBlock?.type === "articleFrame") {
    marketBlock.media = [];
    marketBlock.pullQuote = {
      required: false,
      placements: [
        {
          anchor: "center",
          span: { min: 2, preferred: 2, max: 2 },
          vertical: "middle",
          collapse: "omit",
          crop: "preserve",
          wrapsText: true,
        },
      ],
    };
  }

  return plan;
}

function findPlanBlock(plan: EditionLayoutPlan, blockId: string): EditionLayoutPlan["pages"][number]["regions"][number]["blocks"][number] | undefined {
  return plan.pages.flatMap((page) => page.regions).flatMap((region) => region.blocks).find((block) => block.id === blockId);
}

function findPlanRegion(plan: EditionLayoutPlan, regionId: string): EditionLayoutPlan["pages"][number]["regions"][number] | undefined {
  return plan.pages.flatMap((page) => page.regions).find((region) => region.id === regionId);
}

function cloneLayoutPlan(plan: EditionLayoutPlan): EditionLayoutPlan {
  return JSON.parse(JSON.stringify(plan)) as EditionLayoutPlan;
}
