import { newsroomHref, toPublicNewsroomPath } from "./newsroom-base-path";

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
  { id: "overview", label: "Overview", detail: "Desk home", href: newsroomHref(), mobilePrimary: true },
  { id: "assignments", label: "Assignments", detail: "Work queue", href: newsroomHref("assignments"), mobilePrimary: true },
  { id: "references", label: "References", detail: "Knowledge base", href: newsroomHref("references"), mobilePrimary: true },
  { id: "messages", label: "Messages", detail: "Forum", href: newsroomHref("messages") },
  { id: "insights", label: "Insights", detail: "Research threads", href: newsroomHref("insights") },
  { id: "topics", label: "Topics", detail: "Taxonomy", href: newsroomHref("topics"), mobilePrimary: true },
  { id: "concepts", label: "Concepts", detail: "Ontology", href: newsroomHref("concepts") },
  { id: "administration", label: "Administration", detail: "Users & policies", href: newsroomHref("administration") },
];

export const NEWSROOM_MOBILE_PRIMARY_NAV = NEWSROOM_OPS_NAV.filter((item) => item.mobilePrimary);

export function getNewsroomNavHref(href: string, demo?: boolean): string {
  const path = toPublicNewsroomPath(href);
  if (!demo) return path;
  const url = new URL(path, "http://localhost");
  url.searchParams.set("demo", "1");
  return `${url.pathname}${url.search}`;
}
