import { notFound, redirect } from "next/navigation";
import { ItemPageView } from "../../../../../components/article-page";
import { getCachedEditionItem, loadCachedEditionContent } from "../../../../../lib/cached-content-repository";
import { getEditionDatePath, parseEditionArticleRoute } from "../../../../../lib/edition-routes";
import { buildPresentationFooterEntries } from "../../../../../lib/presentation-footer";
import { SITE_BRAND } from "../../../../../lib/site-brand";
// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 3600;

type DateScopedArticlePageProps = {
  params: Promise<{
    year: string;
    month: string;
    day: string;
    articleSlug: string;
  }>;
};

export async function generateMetadata({ params }: DateScopedArticlePageProps) {
  const { year, month, day, articleSlug } = await params;
  const route = parseEditionArticleRoute({ year, month, day, articleSlug });
  if (!route) return {};

  const item = await getCachedEditionItem({
    editionDate: route.editionDate,
    itemSlug: route.articleSlug,
  });
  if (!item) return {};

  return {
    title: `${item.type === "article" ? item.headline : item.title} | ${SITE_BRAND.articleTitleSuffix}`,
    description: item.deck,
  };
}

export default async function DateScopedArticlePage({ params }: DateScopedArticlePageProps) {
  const { year, month, day, articleSlug } = await params;
  const route = parseEditionArticleRoute({ year, month, day, articleSlug });
  if (!route) notFound();
  if (!route.isCanonical) redirect(route.canonicalPath);

  const content = await loadCachedEditionContent({ editionDate: route.editionDate });
  const item = content.items.find((candidate) => candidate.slug === route.articleSlug);
  if (!item) notFound();
  const editionBasePath = getEditionDatePath(route.editionDate);

  return (
    <ItemPageView
      editionDate={content.editionDate}
      editionFooter={{
        editionBasePath,
        entries: buildPresentationFooterEntries(content),
        subtitle: SITE_BRAND.id === "threat-intelligence" ? "" : (content.description?.trim() || "Inside Papyrus"),
        title: SITE_BRAND.id === "threat-intelligence" ? "ANTHUS THREAT INTELLIGENCE" : undefined,
      }}
      item={item}
      backHref={`${editionBasePath}#${item.slug}`}
    />
  );
}
