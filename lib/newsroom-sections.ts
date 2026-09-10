import type { NewsroomSectionRecord } from "./category-repository";
import { getNewsroomNavHref } from "./newsroom-nav";

const SECTION_SHORT_TITLE_FALLBACKS: Record<string, string> = {
  news: "News",
  business: "Business",
  technology: "Technology",
  science: "Science",
  methods: "Methods",
  history: "History",
  opinion: "Opinion",
  world: "World",
  arts: "Arts",
  sports: "Sports",
  education: "Education",
  health: "Health",
  security: "Security",
  "law-policy": "Law & Policy",
  labor: "Labor",
  "field-notes": "Field Notes",
  "strangler-control": "Host encirclement",
  "mycelial-signals": "Network routing",
};

export function normalizeNewsroomSectionType(value: string | null | undefined): "canonical" | "floating" {
  return value === "floating" || value === "rotating" ? "floating" : "canonical";
}

export function isEnabledNewsroomSection(section: NewsroomSectionRecord): boolean {
  return section.enabled !== false && section.enabledStatus !== "disabled";
}

export function sortNewsroomSections(sections: NewsroomSectionRecord[]): NewsroomSectionRecord[] {
  return [...sections].sort((left, right) => {
    const typeDiff = (normalizeNewsroomSectionType(left.type) === "canonical" ? 0 : 1)
      - (normalizeNewsroomSectionType(right.type) === "canonical" ? 0 : 1);
    if (typeDiff !== 0) return typeDiff;
    const orderDiff = (left.sortOrder ?? 999999) - (right.sortOrder ?? 999999);
    if (orderDiff !== 0) return orderDiff;
    return left.title.localeCompare(right.title);
  });
}

export function displayNewsroomSectionShortTitle(section: NewsroomSectionRecord): string {
  const explicit = section.shortTitle?.trim();
  if (explicit) return explicit;
  return SECTION_SHORT_TITLE_FALLBACKS[section.id] ?? section.id.replace(/-/g, " ");
}

export function buildNewsroomSectionHref(sectionId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/sections/${encodeURIComponent(sectionId)}`, demo);
}
