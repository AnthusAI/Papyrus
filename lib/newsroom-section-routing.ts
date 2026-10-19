import type { NewsDeskTab } from "../components/topic-steering-workspace";

/** The organizer restores the existing taxonomy editor; legacy sites retain their aliases. */
export function resolveNewsDeskTab(
  sectionValue: string | string[] | null | undefined,
  legacyTabValue: string | string[] | null | undefined,
  organizer = false,
): NewsDeskTab {
  const section = Array.isArray(sectionValue) ? sectionValue[0] : sectionValue;
  const legacyTab = Array.isArray(legacyTabValue) ? legacyTabValue[0] : legacyTabValue;
  const raw = section ?? (legacyTab === "categories" ? "topics" : legacyTab);
  const value = raw === "users" || raw === "doctrine" ? "administration"
    : raw === "desks" && !organizer ? "topics" : raw;
  switch (value) {
    case "desks": case "administration": case "topics": case "concepts":
    case "references": case "messages": case "assignments": case "search":
      return value;
    default: return "overview";
  }
}
