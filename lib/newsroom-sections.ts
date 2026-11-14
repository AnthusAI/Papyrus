import type { NewsroomSectionRecord } from "./category-repository";
import { getNewsroomNavHref } from "./newsroom-nav";

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
  return section.shortTitle?.trim() || section.title;
}

export function buildNewsroomSectionHref(sectionId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/sections/${encodeURIComponent(sectionId)}`, demo);
}

export type NewsroomDeskKind = "core" | "rotating";
export type NewsroomDeskOption = { value: string; label: string; kind: NewsroomDeskKind };

export function newsroomDeskKind(section: NewsroomSectionRecord): NewsroomDeskKind {
  return normalizeNewsroomSectionType(section.type) === "canonical" ? "core" : "rotating";
}

/** The desks a story or assignment can be placed on: the same enabled, ordered desks the Overview page lists. */
export function newsroomDeskOptions(sections: NewsroomSectionRecord[]): NewsroomDeskOption[] {
  return sortNewsroomSections(sections).filter(isEnabledNewsroomSection).map(section => ({ value: section.id, label: section.title, kind: newsroomDeskKind(section) }));
}
