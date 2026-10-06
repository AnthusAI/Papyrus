import { NewsroomArticleEditor } from "../../../../components/newsroom-article-editor";

export const dynamic = "force-dynamic";

type NewsroomArticleEditorPageProps = {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{ demo?: string | string[] }>;
};

export default async function NewsroomArticleEditorPage({ params, searchParams }: NewsroomArticleEditorPageProps) {
  const { id } = await params;
  const resolved = await searchParams;
  const demoValue = Array.isArray(resolved?.demo) ? resolved?.demo[0] : resolved?.demo;
  return <NewsroomArticleEditor articleId={decodeURIComponent(id)} demo={demoValue === "1"} />;
}
