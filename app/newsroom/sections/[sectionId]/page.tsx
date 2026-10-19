import { notFound } from "next/navigation";
import { NewsroomBoardView } from "../../../../components/newsroom-board-view";

export const dynamic = "force-dynamic";

type NewsroomDeepSectionPageProps = {
  params: Promise<{ sectionId: string }>;
};

export default async function NewsroomDeepSectionPage({ params }: NewsroomDeepSectionPageProps) {
  const { sectionId } = await params;
  const normalizedSectionId = decodeURIComponent(sectionId ?? "").trim();
  if (!normalizedSectionId) notFound();

  return <NewsroomBoardView subject="desk" deskId={normalizedSectionId} />;
}
