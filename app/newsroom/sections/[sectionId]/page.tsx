import { notFound } from "next/navigation";
import { resolveActiveSiteBrand } from "../../../../lib/site-brand-tenant";
import { NewsroomBoardView } from "../../../../components/newsroom-board-view";
import { NewsDeskPage } from "../../../../components/news-desk-page";

export const dynamic = "force-dynamic";

type NewsroomDeepSectionPageProps = {
  params: Promise<{ sectionId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function NewsroomDeepSectionPage({ params, searchParams }: NewsroomDeepSectionPageProps) {
  const { sectionId } = await params;
  const normalizedSectionId = decodeURIComponent(sectionId ?? "").trim();
  if (!normalizedSectionId) notFound();

  if (resolveActiveSiteBrand().newsroomLayout === "organizer") return <NewsroomBoardView subject="desk" deskId={normalizedSectionId} />;
  return <NewsDeskPage sectionPageId={normalizedSectionId} searchParams={searchParams} />;
}
