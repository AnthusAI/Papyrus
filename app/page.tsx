import { PresentationShell } from "../components/presentation-shell";
import { contentRepository, getScenarioIdParam } from "../lib/content-repository";
import type { EditionContent } from "../lib/content-types";
import { createEditionSectionPlan } from "../lib/edition-sections";
import { getEditionDatePath } from "../lib/edition-routes";
import { normalizeEditionLayoutPlan } from "../lib/layout-plan";
import {
  loadPublicPlaceholderSections,
  loadPublicPlaceholderTopics,
  type PublicPlaceholderSection,
  type PublicPlaceholderTopic,
} from "../lib/public-placeholder-config";
import type { PublicationItem } from "../lib/publication-items";
import { SITE_BRAND } from "../lib/site-brand";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

type HomePageProps = {
  searchParams?: Promise<{
    scenario?: string | string[];
    code?: string | string[];
    state?: string | string[];
    error?: string | string[];
  }>;
};

export default async function Home({ searchParams }: HomePageProps) {
  const resolvedSearchParams = await searchParams;
  const scenarioId = getScenarioIdParam(resolvedSearchParams?.scenario);
  if (!scenarioId) {
    if (hasOAuthRedirectParams(resolvedSearchParams)) {
      const mastheadHomeHref = await loadFirstPublishedEditionPath();
      const content = await loadLatestGraphQLEdition();
      if (!content || content.items.length === 0) return <PresentationShell content={createEmptyGraphQLEdition()} />;
      return (
        <PresentationShell
          content={content}
          editionBasePath={getEditionDatePath(content.editionDate)}
          mastheadHomeHref={mastheadHomeHref}
        />
      );
    }

    const latestEdition = await contentRepository.getLatestPublishedEdition();
    if (latestEdition) redirect(getEditionDatePath(latestEdition.editionDate));
    return <PresentationShell content={createEmptyGraphQLEdition()} />;
  }

  const content = await loadHomeContent(scenarioId);
  if (content.items.length === 0) return <PresentationShell content={createEmptyGraphQLEdition()} />;
  return <PresentationShell content={content} />;
}

async function loadLatestGraphQLEdition(): Promise<EditionContent | null> {
  const latestEdition = await contentRepository.getLatestPublishedEdition();
  if (!latestEdition) return null;
  return contentRepository.loadEditionContent({ editionDate: latestEdition.editionDate });
}

async function loadFirstPublishedEditionPath(): Promise<string | undefined> {
  const firstEdition = await contentRepository.getFirstPublishedEdition();
  if (!firstEdition) return undefined;
  return getEditionDatePath(firstEdition.editionDate);
}

async function loadHomeContent(scenarioId: string | null): Promise<EditionContent> {
  try {
    return await contentRepository.loadEditionContent({ scenarioId });
  } catch (error) {
    if (scenarioId || !isMissingGraphQLEditionError(error)) throw error;
    return createEmptyGraphQLEdition();
  }
}

function createEmptyGraphQLEdition(): EditionContent {
  const placeholderSlug = "empty-edition-placeholder";
  const configuredSections = loadPublicPlaceholderSections();
  const publicTopics = loadPublicPlaceholderTopics();
  const sectionItems = createPlaceholderSectionItems(configuredSections);
  const topicItems = createPlaceholderTopicItems(publicTopics);
  const sectionsCta = createPlaceholderCtaItem({
    slug: "empty-edition-sections-newsroom",
    title: "Manage sections in Newsroom",
    deck: "Canonical and rotating sections are managed from the Newsroom.",
    href: "/newsroom/sections",
    group: "sections",
    ctaLabel: "Manage sections in Newsroom",
  });
  const topicsCta = createPlaceholderCtaItem({
    slug: "empty-edition-topics-newsroom",
    title: "Curate topics in Newsroom",
    deck: "The AI/ML technology that powers the knowledge base is curated from the Newsroom.",
    href: "/newsroom/topics",
    group: "topics",
    ctaLabel: "Curate topics in Newsroom",
  });
  const items: EditionContent["items"] = [
    createEmptyEditionLandingItem(placeholderSlug),
    ...sectionItems,
    sectionsCta,
    ...topicItems,
    topicsCta,
  ];

  return {
    id: "empty-graphql-edition",
    source: "graphql",
    placeholderMode: "emptyEdition",
    title: SITE_BRAND.appTitle,
    editionDate: new Date().toISOString().slice(0, 10),
    description: "No published GraphQL edition is available yet.",
    items,
    sections: createEditionSectionPlan(items),
    layoutPlan: normalizeEditionLayoutPlan({
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
                  itemIds: [...sectionItems.map((item) => item.slug), sectionsCta.slug],
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
                  itemIds: [...topicItems.map((item) => item.slug), topicsCta.slug],
                },
              ],
            },
          ],
        },
      ],
    }, "EmptyGraphQLEdition.layoutPlan"),
  };
}

function createEmptyEditionLandingItem(slug: string): PublicationItem {
  return {
    type: "article",
    slug,
    shortSlug: "EMPTY",
    section: "Newsroom",
    headline: "An Autonomous Newsroom for Human-Steered Publishing",
    deck: "An automated newsroom that turns research, judgment, and policy into blog-first editions.",
    byline: SITE_BRAND.placeholderByline,
    dateline: "SANDBOX",
    image: {
      src: "/papyrus-plant-placeholder.png",
      themeVariants: {
        dark: {
          src: "/papyrus-plant-placeholder-dark.png",
        },
      },
      alt: "Anthus Threat Intelligence emblem",
      credit: "",
      layout: {
        minHeight: 120,
        preferredHeight: 320,
        maxHeight: 440,
        aspectRatio: 0.785,
        crop: "contain",
        wrapsText: true,
        inlineFloat: {
          minColumnCount: 4,
          columnSpan: 1,
          widthRatio: 0.42,
          narrowWidthRatio: 0.34,
          maxWidthRatio: 0.42,
          minWidth: 72,
        },
      },
    },
    body: [
      `${SITE_BRAND.articleTitleSuffix} helps a publication do what good journalism promises: establish the facts, add context, identify trends, and turn scattered information into something readers can understand.`,
      "Instead of starting with a blank article form, you start by steering the newsroom. You define the mission, set editorial policies, choose sections and topics, and tell research agents what questions or trends deserve attention.",
      "As the system finds source material, you curate what it learns. You rate and vote on references, comment on whether they are relevant or reliable, and help the knowledge base decide what should inform future coverage.",
      "Editor agents use that guidance to plan coverage and create assignments. Reporter agents gather context, copywriting agents draft stories, and layout agents assemble editions for human proofing and approval.",
      "You can steer lightly, give explicit research or writing assignments, or write directly when a piece needs a human voice. If you take your hands off the wheel, the newsroom keeps moving in the direction set by its mission, policies, and curated knowledge.",
      "This is the default placeholder for a fresh installation. Once an edition is published, this front page will become the publication itself.",
    ],
  };
}

function createPlaceholderSectionItems(sections: PublicPlaceholderSection[]): PublicationItem[] {
  return sections.map((section) => ({
    type: "sectionHeader",
    slug: `empty-edition-section-${section.id}`,
    section: section.type === "canonical" ? "Canonical Section" : "Rotating Section",
    title: section.title,
    deck: section.shortTitle,
    metadata: {
      placeholderKind: "section",
      placeholderGroup: section.type === "canonical" ? "canonical" : "rotating",
      placeholderType: section.type === "canonical" ? "canonical" : "rotating",
    },
  }));
}

function createPlaceholderTopicItems(topics: PublicPlaceholderTopic[]): PublicationItem[] {
  return topics.map((topic) => ({
    type: "sectionHeader",
    slug: `empty-edition-topic-${topic.key}`,
    section: "Inferred Topic",
    title: topic.title,
    deck: topic.shortTitle,
    body: [topic.description],
    metadata: {
      placeholderKind: "topic",
      placeholderGroup: "topics",
    },
  }));
}

function createPlaceholderCtaItem({
  slug,
  title,
  deck,
  href,
  group,
  ctaLabel,
}: {
  slug: string;
  title: string;
  deck: string;
  href: string;
  group: string;
  ctaLabel: string;
}): PublicationItem {
  return {
    type: "promo",
    slug,
    section: "Newsroom",
    title,
    deck,
    href,
    metadata: {
      placeholderKind: "cta",
      placeholderGroup: group,
      ctaLabel,
    },
  };
}

function isMissingGraphQLEditionError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("No published GraphQL edition found");
}

function hasOAuthRedirectParams(searchParams: Awaited<HomePageProps["searchParams"]>): boolean {
  return hasParam(searchParams?.error) || (hasParam(searchParams?.code) && hasParam(searchParams?.state));
}

function hasParam(value: string | string[] | null | undefined): boolean {
  if (Array.isArray(value)) return value.some(Boolean);
  return Boolean(value);
}
