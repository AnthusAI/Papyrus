import { NewsroomBoardView } from "../../../components/newsroom-board-view";
import { resolveActiveSiteBrand } from "../../../lib/site-brand-tenant";
import { NewsroomArticlesView } from "../../../components/newsroom-articles-view";

export const dynamic = "force-dynamic";

type NewsroomArticlesPageProps = {
  searchParams?: Promise<{ demo?: string | string[] }>;
};

export default async function NewsroomArticlesPage({ searchParams }: NewsroomArticlesPageProps) {
  const resolved = await searchParams;
  const demoValue = Array.isArray(resolved?.demo) ? resolved?.demo[0] : resolved?.demo;
  if (resolveActiveSiteBrand().newsroomLayout === "organizer" && demoValue !== "1") return <NewsroomBoardView subject="contentItem" />;
  return <NewsroomArticlesView demo={demoValue === "1"} />;
}
