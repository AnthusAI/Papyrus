import { notFound } from "next/navigation";
import { ArticlePageView } from "../../../components/article-page";
import { getCachedArticle } from "../../../lib/cached-content-repository";
import { generateArticleStaticParams } from "../../../lib/reader-static-params";
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
  const { slug } = await params;
  const article = await getCachedArticle(slug);
  if (!article) return {};
  return {
    title: `${article.headline} | ${SITE_BRAND.articleTitleSuffix}`,
    description: article.deck,
  };
}

export default async function ArticlePage({ params }: ArticlePageProps) {
  const { slug } = await params;
  const article = await getCachedArticle(slug);
  if (!article) notFound();

  return <ArticlePageView article={article} backHref="/" />;
}
