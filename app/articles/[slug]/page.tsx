import { notFound } from "next/navigation";
import { getSiteRenderer } from "../../../lib/site-renderer";
import { getCachedArticle, getCachedVideoScript } from "../../../lib/cached-content-repository";
import { generateArticleStaticParams, siteServesNextReaderRoutes } from "../../../lib/reader-static-params";
import { SITE_BRAND } from "../../../lib/site-brand";

// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 3600;

export async function generateStaticParams() {
  return generateArticleStaticParams();
}

type ArticlePageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: ArticlePageProps) {
  if (!siteServesNextReaderRoutes()) return {};
  const { slug } = await params;
  const article = await getCachedArticle(slug);
  if (!article) return {};
  return {
    title: `${article.headline} | ${SITE_BRAND.articleTitleSuffix}`,
    description: article.deck,
  };
}

export default async function ArticlePage({ params }: ArticlePageProps) {
  if (!siteServesNextReaderRoutes()) notFound();
  const { slug } = await params;
  const [article, videoScript] = await Promise.all([getCachedArticle(slug), getCachedVideoScript(slug)]);
  if (!article) notFound();

  const siteRenderer = getSiteRenderer();
  return <siteRenderer.renderArticle article={article} videoScript={videoScript} backHref="/" />;
}
