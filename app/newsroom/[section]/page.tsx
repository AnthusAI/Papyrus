import { notFound, redirect } from "next/navigation";
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
  "administration",
  "topics",
  "concepts",
  "references",
  "insights",
  "messages",
  "assignments",
  "search",
]);

export default async function NewsDeskSectionPage({ params, searchParams }: NewsDeskSectionPageProps) {
  const { section } = await params;
  if (section === "users") redirect("/newsroom/administration/users");
  if (section === "doctrine") redirect("/newsroom/administration/policies");
  if (section === "desks") redirect("/newsroom/topics");
  if (!NEWS_DESK_ROUTE_SECTIONS.has(section as NewsDeskTab)) notFound();
  return <NewsDeskPage section={section} searchParams={searchParams} />;
}
