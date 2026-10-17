import { notFound } from "next/navigation";
import { resolveActiveSiteBrand } from "../../../lib/site-brand-tenant";
import { NewsroomBoardView } from "../../../components/newsroom-board-view";

export const dynamic = "force-dynamic";

export default function NewsroomWorkPage() {
  if (resolveActiveSiteBrand().newsroomLayout !== "organizer") notFound();
  return <NewsroomBoardView />;
}
