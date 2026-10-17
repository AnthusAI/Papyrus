import { NewsroomArticlesView } from "../../../components/newsroom-articles-view";

export const dynamic = "force-dynamic";

type NewsroomArticlesPageProps = {
  searchParams?: Promise<{ demo?: string | string[] }>;
};

export default async function NewsroomArticlesPage({ searchParams }: NewsroomArticlesPageProps) {
  const resolved = await searchParams;
  const demoValue = Array.isArray(resolved?.demo) ? resolved?.demo[0] : resolved?.demo;
  return <NewsroomArticlesView demo={demoValue === "1"} />;
}
