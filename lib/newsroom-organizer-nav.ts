import { contentItemBoardPathSegment } from "./newsroom-board";
import { getContentItemName } from "./site-brand";

const contentItemPluralLowercase = getContentItemName().plural.toLowerCase();
export type OrganizerDestination = {
  key: string; label: string; description: string; path: string;
  access?: "admin"; primary?: boolean; unavailable?: string; alsoActiveOnPaths?: readonly string[];
};
export const ORGANIZER_NAV_GROUPS: readonly { title: string; items: readonly OrganizerDestination[] }[] = [
  { title: "Editorial work", items: [
    { key: "overview", label: "Needs me", description: "See what needs you: drafts, references and reviews.", path: "/newsroom", primary: true },
    { key: "articles", label: getContentItemName().plural, description: `Follow ${contentItemPluralLowercase} across their stages and open one to write or revise it.`, path: `/newsroom/${contentItemBoardPathSegment()}`, alsoActiveOnPaths: ["/newsroom/articles"], primary: true },
    { key: "assignments", label: "Assignments", description: "Follow research and reporting work across its statuses and claim it.", path: "/newsroom/assignments" },
    { key: "drafts", label: "Drafts", description: "Read the story drafts that AI proposes, then accept or reject them.", path: "/newsroom/administration/proposals" },
    { key: "messages", label: "Messages", description: "Read and reply to newsroom conversations.", path: "/newsroom/messages", primary: true },
  ] },
  { title: "Research & knowledge", items: [
    { key: "references", label: "References", description: "Inspect sources and make editorial inclusion decisions.", path: "/newsroom/references", primary: true },
    { key: "concepts", label: "Concepts", description: "A wiki of the entities in the knowledge graph.", path: "/newsroom/concepts" },
    { key: "sections", label: "Sections", description: "Organize the publication’s sections and its ontology.", path: "/newsroom/administration/sections" },
    { key: "desks", label: "Taxonomy", description: "Maintain topic sets and category versions, and review topic proposals.", path: "/newsroom/desks", alsoActiveOnPaths: ["/newsroom/topics"] },
  ] },
  { title: "Administration", items: [
    { key: "administration", label: "Administration", description: "Policies, procedures, users and settings.", path: "/newsroom/administration", alsoActiveOnPaths: ["/newsroom/administration/policies", "/newsroom/administration/procedures", "/newsroom/administration/users"] },
  ] },
];
const all = ORGANIZER_NAV_GROUPS.flatMap(group => group.items);
export const ORGANIZER_PRIMARY_NAV = ["overview", "articles", "references", "messages"].map(key => all.find(item => item.key === key)!);

export const ORGANIZER_SETTINGS_DESTINATION = {
  label: "Settings", path: "/newsroom/settings", description: "Theme, motion and interface preferences.",
} as const;
