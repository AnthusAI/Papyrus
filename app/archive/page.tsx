import { notFound } from "next/navigation";
import { editionsEnabled } from "../../lib/site-brand";
import { ArchiveShell } from "../../components/archive-shell";
import { ArchiveGrid } from "../../components/archive-grid";
import { loadArchiveEditionPreviews } from "../../lib/archive-data";
import { ARCHIVE_BATCH_SIZE } from "../../lib/archive-types";

// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 60;

export default async function ArchivePage() {
  if (!editionsEnabled()) notFound();
  const initialBatch = await loadArchiveEditionPreviews({ limit: ARCHIVE_BATCH_SIZE });

  return (
    <ArchiveShell>
      <header className="masthead archive-header" aria-describedby="archive-description" aria-labelledby="archive-title">
        <div className="masthead__rule archive-header__rule" />
        <h1 id="archive-title">
          <span>ARCHIVE</span>
        </h1>
        <p className="archive-description" id="archive-description">Previous editions</p>
      </header>
      <ArchiveGrid initialNextCursor={initialBatch.nextCursor ?? null} initialPreviews={initialBatch.previews} />
    </ArchiveShell>
  );
}
