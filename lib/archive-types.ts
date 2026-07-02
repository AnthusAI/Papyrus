import type { EditionRouteSummary } from "./content-types";

export const ARCHIVE_BATCH_SIZE = 12;
export const ARCHIVE_PREVIEW_WIDTH = 1280;
export const ARCHIVE_PREVIEW_HEIGHT = 900;

export type ArchiveEditionPreview = {
  edition: EditionRouteSummary;
  href: string;
};

export type ArchiveEditionsResponse = {
  previews: ArchiveEditionPreview[];
  nextCursor?: string | null;
};
