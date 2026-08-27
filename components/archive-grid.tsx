"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ARCHIVE_BATCH_SIZE, type ArchiveEditionPreview, type ArchiveEditionsResponse } from "../lib/archive-types";

type ArchiveGridProps = {
  initialPreviews: ArchiveEditionPreview[];
  initialNextCursor?: string | null;
};

export function ArchiveGrid({ initialPreviews, initialNextCursor = null }: ArchiveGridProps) {
  const [previews, setPreviews] = useState(initialPreviews);
  const [nextCursor, setNextCursor] = useState<string | null>(initialNextCursor);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loading) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/archive/editions?cursor=${encodeURIComponent(nextCursor)}&limit=${ARCHIVE_BATCH_SIZE}`);
      if (!response.ok) throw new Error(`Archive request failed: ${response.status}`);
      const payload = (await response.json()) as ArchiveEditionsResponse;
      setPreviews((current) => {
        const seen = new Set(current.map((preview) => preview.edition.id));
        const additions = payload.previews.filter((preview) => !seen.has(preview.edition.id));
        return [...current, ...additions];
      });
      setNextCursor(payload.nextCursor ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Archive request failed");
    } finally {
      setLoading(false);
    }
  }, [loading, nextCursor]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !nextCursor) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        void loadMore();
      }
    }, { rootMargin: "900px 0px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore, nextCursor]);

  return (
    <section className="archive-grid-shell" aria-label="Edition archive">
      {previews.length === 0 ? (
        <p className="archive-empty">No published editions are available yet.</p>
      ) : (
        <div className="archive-grid" data-archive-grid="true">
          {previews.map((preview) => (
            <article className="archive-card" data-archive-edition-id={preview.edition.id} key={preview.edition.id}>
              <Link className="archive-card__hit-area" href={preview.href} aria-label={`Open ${preview.edition.title} from ${preview.edition.editionDate}`} />
              <header className="archive-card__label">
                <time dateTime={preview.edition.editionDate}>{formatArchiveDate(preview.edition.editionDate)}</time>
                <span>Edition</span>
              </header>
              <div className="archive-card__summary">
                <h2>{preview.edition.title}</h2>
                {preview.edition.description ? <p>{preview.edition.description}</p> : null}
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="archive-sentinel" data-archive-sentinel="true" data-has-next-cursor={nextCursor ? "true" : "false"} ref={sentinelRef}>
        {loading ? "Loading editions" : error ?? (nextCursor ? "More editions" : "End of archive")}
      </div>
    </section>
  );
}

function formatArchiveDate(editionDate: string): string {
  const date = new Date(`${editionDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return editionDate;
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}
