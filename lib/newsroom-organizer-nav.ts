import { contentItemBoardPathSegment } from "./newsroom-board";
import { getContentItemName } from "./site-brand";

const contentItemPluralLowercase = getContentItemName().plural.toLowerCase();
export type OrganizerDestination = {
  key: string; label: string; description: string; path: string;
  access?: "admin"; primary?: boolean; unavailable?: string; alsoActiveOnPaths?: readonly string[];
};
export const ORGANIZER_NAV_GROUPS: readonly { title: string; items: readonly OrganizerDestination[] }[] = [
  { title: "Editorial work", items: [
    { key: "overview", label: "Overview", description: "See the desk and choose where to begin.", path: "/newsroom", primary: true },
    { key: "articles", label: getContentItemName().plural, description: `Follow ${contentItemPluralLowercase} across their stages and open one to write or revise it.`, path: `/newsroom/${contentItemBoardPathSegment()}`, alsoActiveOnPaths: ["/newsroom/articles"], primary: true },
    { key: "assignments", label: "Assignments", description: "Follow research and reporting work across its statuses and claim it.", path: "/newsroom/assignments" },
    { key: "messages", label: "Messages", description: "Read and reply to newsroom conversations.", path: "/newsroom/messages", primary: true },
    { key: "insights", label: "Insights", description: "Discuss findings and research threads.", path: "/newsroom/insights" },
  ] },
  { title: "Research & knowledge", items: [
    { key: "references", label: "References", description: "Inspect sources and make editorial inclusion decisions.", path: "/newsroom/references", primary: true },
    { key: "desks", label: "Taxonomy", description: "Maintain topic sets and category versions.", path: "/newsroom/desks" },
    { key: "topics", label: "Topic proposals", description: "Review suggested changes to coverage.", path: "/newsroom/topics" },
    { key: "concepts", label: "Concepts", description: "Explore knowledge entities and relationships.", path: "/newsroom/concepts" },
    { key: "search", label: "Knowledge search", description: "Find evidence across the knowledge base.", path: "/newsroom/search" },
  ] },
  { title: "Administration", items: [
    { key: "policies", label: "Policies", description: "Set publication and category guidance.", path: "/newsroom/administration/policies" },
    { key: "sections", label: "Sections", description: "Organize the publication’s sections.", path: "/newsroom/administration/sections" },
    { key: "procedures", label: "Procedures", description: "Manage procedure definitions and versions.", path: "/newsroom/administration/procedures", access: "admin" },
    { key: "users", label: "Users & identity merging", description: "Review people, roles and identity merges.", path: "/newsroom/administration/users", access: "admin" },
    { key: "administration", label: "Administration", description: "Open the existing CMS settings workspace.", path: "/newsroom/administration" },
  ] },
];
const all = ORGANIZER_NAV_GROUPS.flatMap(group => group.items);
export const ORGANIZER_PRIMARY_NAV = ["overview", "articles", "references", "messages"].map(key => all.find(item => item.key === key)!);

export const ORGANIZER_SETTINGS_DESTINATION = {
  label: "Settings", path: "/newsroom/settings", description: "Theme, motion and interface preferences.",
} as const;
