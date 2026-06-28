import { getEditionSectionItems } from "./edition-sections";
import type { EditionContent } from "./content-types";
import type { PublicationItem } from "./publication-items";

export type PresentationFooterEntry = {
  section: string;
  articleSlug: string;
  articleTitle: string;
};

export type PresentationFooterUtilityEntry =
  | {
      id: "archive";
      label: string;
      href: string;
      disabled: false;
    }
  | {
      id: "newsDesk";
      label: string;
      href: string;
      disabled: false;
    }
  | {
      id: "settings";
      label: string;
      href: string;
      disabled: false;
    }
  | {
      id: "login";
      label: string;
      disabled: true;
    };

export type PresentationFooterGeometry = {
  height: number;
  marginTop: number;
  rowHeight: number;
  sectionColumns: number;
  sectionRows: number;
};

export const PRESENTATION_FOOTER_UTILITIES: PresentationFooterUtilityEntry[] = [
  { id: "archive", label: "Archive", href: "/archive", disabled: false },
  { id: "newsDesk", label: "Newsroom", href: "/newsroom", disabled: false },
  { id: "settings", label: "Settings", href: "/settings", disabled: false },
  { id: "login", label: "LOGIN", disabled: true },
];

export function buildPresentationFooterEntries(content: EditionContent): PresentationFooterEntry[] {
  const entries: PresentationFooterEntry[] = [];
  const seenSections = new Set<string>();

  for (const section of content.sections) {
    const sectionKey = section.label.trim().toLowerCase();
    if (!sectionKey || seenSections.has(sectionKey)) continue;

    const leadItem = getEditionSectionItems(section, content.items).find((item) => isFooterEligibleItem(item));
    if (!leadItem) continue;

    seenSections.add(sectionKey);
    entries.push({
      section: section.label,
      articleSlug: leadItem.slug,
      articleTitle: getPresentationFooterItemTitle(leadItem),
    });
  }

  return entries;
}

export function getPresentationFooterGrid(entryCount: number, maxColumns = 4): Pick<PresentationFooterGeometry, "sectionColumns" | "sectionRows"> {
  const sectionColumns = entryCount === 0 ? 1 : Math.min(entryCount, Math.max(1, maxColumns));
  const sectionRows = entryCount === 0 ? 0 : Math.ceil(entryCount / sectionColumns);
  return { sectionColumns, sectionRows };
}

export function getPresentationFooterSubtitle(content: EditionContent): string {
  const description = content.description?.trim();
  return description && description.length > 0 ? description : "Inside Papyrus";
}

function isFooterEligibleItem(item: PublicationItem): boolean {
  return item.type === "article" || item.type === "brief";
}

function getPresentationFooterItemTitle(item: PublicationItem): string {
  return item.type === "article" ? item.headline : item.title;
}
