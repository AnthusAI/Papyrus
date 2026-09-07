export type NewsroomNavTabId =
  | "overview"
  | "messages"
  | "insights"
  | "assignments"
  | "references"
  | "topics"
  | "concepts"
  | "administration"
  | "search"
  | "desks";

export type NewsroomNavItem = {
  id: NewsroomNavTabId;
  label: string;
  detail: string;
  href: string;
  mobilePrimary?: boolean;
};

export const NEWSROOM_OPS_NAV: NewsroomNavItem[] = [
  { id: "overview", label: "Overview", detail: "Desk home", href: "/newsroom", mobilePrimary: true },
  { id: "assignments", label: "Assignments", detail: "Work queue", href: "/newsroom/assignments", mobilePrimary: true },
  { id: "references", label: "References", detail: "Knowledge base", href: "/newsroom/references", mobilePrimary: true },
  { id: "messages", label: "Messages", detail: "Forum", href: "/newsroom/messages" },
  { id: "insights", label: "Insights", detail: "Research threads", href: "/newsroom/insights" },
  { id: "topics", label: "Topics", detail: "Taxonomy", href: "/newsroom/topics", mobilePrimary: true },
  { id: "concepts", label: "Concepts", detail: "Ontology", href: "/newsroom/concepts" },
  { id: "administration", label: "Administration", detail: "Users & policies", href: "/newsroom/administration" },
];

export const NEWSROOM_MOBILE_PRIMARY_NAV = NEWSROOM_OPS_NAV.filter((item) => item.mobilePrimary);

export function getNewsroomNavHref(href: string, demo?: boolean): string {
  if (!demo) return href;
  const url = new URL(href, "http://localhost");
  url.searchParams.set("demo", "1");
  return `${url.pathname}${url.search}`;
}
