import { FEED_SURFACE_PROPS } from "./reference-feed";

/** The board's loading state: three columns of pulsing cards in the feed's flat tones and rounded rectangles, with no outlines; below 600 px, the width at which the board stacks, one list of sections. */
export function NewsroomBoardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading board records" className="w-full" data-board-skeleton role="status" {...FEED_SURFACE_PROPS}>
      {Array.from({ length: 3 }, (_, column) => (
        <div className="min-h-64 space-y-3 rounded-[20px] bg-[var(--feed-footer)] p-4" data-board-skeleton-section key={column}>
          <div className="h-4 w-1/2 animate-pulse rounded-full bg-[var(--feed-control)]" />
          {Array.from({ length: 2 }, (_, row) => (
            <div className="h-24 rounded-2xl bg-[var(--feed-card)] p-3" key={row}>
              <div className="h-4 w-3/4 animate-pulse rounded-full bg-[var(--feed-control)]" />
              <div className="mt-3 h-3 w-1/2 animate-pulse rounded-full bg-[var(--feed-control)]" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
