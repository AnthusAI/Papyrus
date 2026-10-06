import { graphqlContentRepository } from "./graphql-content-repository";
import { getRendererKind } from "./site-brand";
import type { RendererConfig } from "./renderer-config";

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

export async function generateEditionDateStaticParams(
  rendererKind: RendererConfig["kind"] = getRendererKind(),
): Promise<EditionDateStaticParam[]> {
  if (rendererKind === "markus") return [];
  if (process.env.NODE_ENV === "development") return [];

  const { editions } = await graphqlContentRepository.listPublishedEditions({ limit: 100 });
  const params: EditionDateStaticParam[] = [];
  for (const edition of editions) {
    const route = editionDateToStaticParam(edition.editionDate);
    if (route) params.push(route);
  }
  return params;
}

export async function generateArticleStaticParams(
  rendererKind: RendererConfig["kind"] = getRendererKind(),
): Promise<Array<{ slug: string }>> {
  if (rendererKind === "markus") return [];
  if (process.env.NODE_ENV === "development") return [];

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
    day: String(Number(match[3])),
  };
}
