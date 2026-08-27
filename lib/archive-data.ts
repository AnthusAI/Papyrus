import { listCachedPublishedEditions } from "./cached-content-repository";
import { getEditionDatePath } from "./edition-routes";
import { ARCHIVE_BATCH_SIZE, type ArchiveEditionsResponse } from "./archive-types";

type ArchiveBatchOptions = {
  limit?: number;
  nextToken?: string | null;
};

export async function loadArchiveEditionPreviews({ limit = ARCHIVE_BATCH_SIZE, nextToken }: ArchiveBatchOptions = {}): Promise<ArchiveEditionsResponse> {
  const safeLimit = clampArchiveLimit(limit);
  const { editions, nextToken: nextCursor } = await listCachedPublishedEditions({
    limit: safeLimit,
    nextToken,
  });
  const previews = editions.map((edition) => ({
    edition,
    href: getEditionDatePath(edition.editionDate),
  }));

  return {
    previews,
    nextCursor,
  };
}

export function clampArchiveLimit(limit: number): number {
  if (!Number.isFinite(limit)) return ARCHIVE_BATCH_SIZE;
  return Math.max(1, Math.min(ARCHIVE_BATCH_SIZE, Math.floor(limit)));
}
