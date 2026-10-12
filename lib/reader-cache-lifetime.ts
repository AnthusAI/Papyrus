/**
 * Seconds a Pretext reader page may be served from a shared cache (Next sends `s-maxage` equal to its `revalidate`).
 * Next needs a literal in each route's `export const revalidate`, so scripts/test-reader-cache-lifetime.ts keeps them equal to this.
 */
export const READER_PAGE_REVALIDATE_SECONDS = 60;
