import type { ContentRepository, EditionContent } from "./content-types";
import { graphqlContentRepository } from "./graphql-content-repository";
import { SITE_BRAND, editionsEnabled } from "./site-brand";
import { getContentSource } from "./site-env";
import type { RendererConfig } from "./renderer-config";

export function siteEnumeratesReaderRoutesAtBuild(): boolean {
  return siteServesNextReaderRoutes() && getContentSource() !== "drafts";
}

export function siteServesNextReaderRoutes(rendererKind: RendererConfig["kind"] = SITE_BRAND.renderer.kind): boolean {
  return rendererKind !== "markus";
}

const MONTH_NAMES = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
] as const;

type EditionDateStaticParam = {
  year: string;
  month: string;
  day: string;
};

const PUBLISHED_EDITION_ENUMERATION_LIMIT = 100;
const DEEP_ROUTE_EDITION_LIMIT = 10;
const RESERVED_DATE_CHILD_SEGMENTS = new Set(["page", "section"]);

type EnumerationRepository = Pick<ContentRepository, "listPublishedEditions" | "loadEditionContent">;

function shouldEnumerateAtBuild(): boolean {
  if (!editionsEnabled()) return false;
  if (process.env.NODE_ENV === "development") return false;
  return siteEnumeratesReaderRoutesAtBuild();
}

export async function generateEditionDateStaticParams(
  repository: EnumerationRepository = graphqlContentRepository,
): Promise<EditionDateStaticParam[]> {
  if (!shouldEnumerateAtBuild()) return [];

  const { editions } = await repository.listPublishedEditions({ limit: PUBLISHED_EDITION_ENUMERATION_LIMIT });
  const params: EditionDateStaticParam[] = [];
  for (const edition of editions) {
    const route = editionDateToStaticParam(edition.editionDate);
    if (route) params.push(route);
  }
  return params;
}

async function loadRecentEditionContents(repository: EnumerationRepository): Promise<EditionContent[]> {
  const { editions } = await repository.listPublishedEditions({ limit: PUBLISHED_EDITION_ENUMERATION_LIMIT });
  const recent = [...editions]
    .sort((left, right) => right.editionDate.localeCompare(left.editionDate))
    .slice(0, DEEP_ROUTE_EDITION_LIMIT);
  return Promise.all(recent.map((edition) => repository.loadEditionContent({ editionDate: edition.editionDate })));
}

export async function generateEditionItemStaticParams(
  repository: EnumerationRepository = graphqlContentRepository,
): Promise<Array<EditionDateStaticParam & { articleSlug: string }>> {
  if (!shouldEnumerateAtBuild()) return [];

  const params: Array<EditionDateStaticParam & { articleSlug: string }> = [];
  for (const content of await loadRecentEditionContents(repository)) {
    const date = editionDateToStaticParam(content.editionDate);
    if (!date) continue;
    for (const item of content.items) {
      if (RESERVED_DATE_CHILD_SEGMENTS.has(item.slug.toLowerCase())) continue;
      params.push({ ...date, articleSlug: item.slug });
    }
  }
  return params;
}

export async function generateEditionPageStaticParams(
  repository: EnumerationRepository = graphqlContentRepository,
): Promise<Array<EditionDateStaticParam & { pageNumber: string }>> {
  if (!shouldEnumerateAtBuild()) return [];

  const params: Array<EditionDateStaticParam & { pageNumber: string }> = [];
  for (const content of await loadRecentEditionContents(repository)) {
    const date = editionDateToStaticParam(content.editionDate);
    if (!date) continue;
    for (let pageNumber = 2; pageNumber <= content.layoutPlan.pages.length; pageNumber += 1) {
      params.push({ ...date, pageNumber: String(pageNumber) });
    }
  }
  return params;
}

export async function generateEditionSectionStaticParams(
  repository: EnumerationRepository = graphqlContentRepository,
): Promise<Array<EditionDateStaticParam & { sectionKey: string }>> {
  if (!shouldEnumerateAtBuild()) return [];

  const params: Array<EditionDateStaticParam & { sectionKey: string }> = [];
  for (const content of await loadRecentEditionContents(repository)) {
    const date = editionDateToStaticParam(content.editionDate);
    if (!date) continue;
    for (const section of content.sections) params.push({ ...date, sectionKey: section.key });
  }
  return params;
}

export async function generateArticleStaticParams(): Promise<Array<{ slug: string }>> {
  if (process.env.NODE_ENV === "development") return [];
  if (!siteEnumeratesReaderRoutesAtBuild()) return [];

  const slugs = await graphqlContentRepository.listArticleSlugs();
  return slugs.map((slug) => ({ slug }));
}

function editionDateToStaticParam(editionDate: string): EditionDateStaticParam | null {
  const match = editionDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const monthIndex = Number(match[2]) - 1;
  const monthName = MONTH_NAMES[monthIndex];
  if (!monthName) return null;

  return {
    year: match[1],
    month: monthName,
    day: match[3],
  };
}
