import { notFound, redirect } from "next/navigation";
import { toPublicNewsroomPath } from "../../../lib/newsroom-base-path";
import { contentItemBoardPathSegment } from "../../../lib/newsroom-board";
import { NewsroomBoardView } from "../../../components/newsroom-board-view";
import { NewsDeskPage } from "../../../components/news-desk-page";
import type { NewsDeskTab } from "../../../components/topic-steering-workspace";

export const dynamic = "force-dynamic";

type NewsDeskSectionPageProps = {
  params: Promise<{ section: string }>;
  searchParams?: Promise<{
    demo?: string | string[];
    panel?: string | string[];
    reference?: string | string[];
    category?: string | string[];
    node?: string | string[];
    assignment?: string | string[];
    message?: string | string[];
    user?: string | string[];
    item?: string | string[];
    q?: string | string[];
    anchorKind?: string | string[];
    anchorId?: string | string[];
    anchorLineageId?: string | string[];
    maxTokens?: string | string[];
    from?: string | string[];
    proposal?: string | string[];
  }>;
};

const NEWS_DESK_ROUTE_SECTIONS = new Set<NewsDeskTab>([
  "desks",
  "administration",
  "topics",
  "concepts",
  "references",
  "messages",
  "assignments",
  "search",
]);

export default async function NewsDeskSectionPage({ params, searchParams }: NewsDeskSectionPageProps) {
  const { section } = await params;
  if (section === "work") redirect(toPublicNewsroomPath(`/newsroom/${contentItemBoardPathSegment()}`));
  if (section === "users") redirect(toPublicNewsroomPath("/newsroom/administration/users"));
  if (section === "doctrine") redirect(toPublicNewsroomPath("/newsroom/administration/policies"));
  if (section === contentItemBoardPathSegment()) return <NewsroomBoardView subject="contentItem" />;
  if (!NEWS_DESK_ROUTE_SECTIONS.has(section as NewsDeskTab)) notFound();
  if (section === "assignments") {
    const resolved = await searchParams;
    if (!resolved?.assignment && resolved?.demo !== "1") return <NewsroomBoardView subject="assignment" />;
  }
  return <NewsDeskPage section={section} searchParams={searchParams} />;
}
