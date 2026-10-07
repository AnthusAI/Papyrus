import { notFound, redirect } from "next/navigation";
import { toPublicNewsroomPath } from "../../../../lib/newsroom-base-path";
import { NewsDeskPage } from "../../../../components/news-desk-page";
import type { NewsDeskTab } from "../../../../components/topic-steering-workspace";

export const dynamic = "force-dynamic";

type NewsDeskNestedSectionPageProps = {
  params: Promise<{ section: string; selection: string[] }>;
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
  }>;
};

const NEWS_DESK_ROUTE_SECTIONS = new Set<NewsDeskTab>([
  "administration",
  "topics",
  "concepts",
  "references",
  "insights",
  "messages",
  "assignments",
]);

export default async function NewsDeskNestedSectionPage({ params, searchParams }: NewsDeskNestedSectionPageProps) {
  const { section, selection } = await params;
  if (section === "users") redirect(toPublicNewsroomPath("/newsroom/administration/users"));
  if (section === "doctrine") redirect(toPublicNewsroomPath("/newsroom/administration/policies"));
  if (section === "administration" && selection[0] === "analysis") redirect(toPublicNewsroomPath("/newsroom/assignments"));
  if (section === "desks") {
    const category = selection[0] ? decodeURIComponent(selection[0]) : null;
    if (category) redirect(toPublicNewsroomPath(`/newsroom/topics?category=${encodeURIComponent(category)}`));
    redirect(toPublicNewsroomPath("/newsroom/topics"));
  }
  if (!NEWS_DESK_ROUTE_SECTIONS.has(section as NewsDeskTab)) notFound();
  return <NewsDeskPage section={section} selectionPath={selection} searchParams={searchParams} />;
}
