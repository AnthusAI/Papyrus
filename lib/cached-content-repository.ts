import { unstable_cache } from "next/cache";
import type { Article } from "./articles";
import type {
  EditionContent,
  EditionRouteSummary,
  GetEditionItemOptions,
  ListPublishedEditionsOptions,
  LoadEditionContentOptions,
  PublishedEditionConnection,
} from "./content-types";
import { graphqlContentRepository } from "./graphql-content-repository";
import { READER_REVALIDATE_SECONDS } from "./reader-route-config";

const bypassReaderCacheInDevelopment = process.env.NODE_ENV === "development";

export const EDITIONS_CACHE_TAG = "editions";
export const ARCHIVE_CACHE_TAG = "archive";
export const ARTICLES_CACHE_TAG = "articles";

export function editionContentCacheTag(editionDate: string): string {
  return `edition:${editionDate}`;
}

export function articleCacheTag(slug: string): string {
  return `article:${slug}`;
}

export function editionItemCacheTag(editionDate: string, itemSlug: string): string {
  return `edition-item:${editionDate}:${itemSlug}`;
}

function withReaderCache<T>(
  cacheKey: string[],
  tags: string[],
  loader: () => Promise<T>,
): Promise<T> {
  if (bypassReaderCacheInDevelopment) return loader();
  return unstable_cache(loader, cacheKey, {
    tags,
    revalidate: READER_REVALIDATE_SECONDS,
  })();
}

export function loadCachedEditionContent(options: LoadEditionContentOptions = {}): Promise<EditionContent> {
  const editionDate = options.editionDate ?? "active";
  const editionSlug = options.editionSlug ?? "";
  return withReaderCache(
    ["reader-edition-content", editionDate, editionSlug],
    editionDate === "active" ? [EDITIONS_CACHE_TAG] : [editionContentCacheTag(editionDate), EDITIONS_CACHE_TAG],
    async () => graphqlContentRepository.loadEditionContent(options),
  );
}

export function getCachedArticle(slug: string): Promise<Article | undefined> {
  return withReaderCache(
    ["reader-article", slug],
    [articleCacheTag(slug), ARTICLES_CACHE_TAG],
    async () => graphqlContentRepository.getArticle(slug),
  );
}

export function getCachedEditionItem(options: GetEditionItemOptions): Promise<import("./publication-items").PublicationItem | undefined> {
  const { editionDate, itemSlug } = options;
  return withReaderCache(
    ["reader-edition-item", editionDate, itemSlug],
    [editionItemCacheTag(editionDate, itemSlug), editionContentCacheTag(editionDate), EDITIONS_CACHE_TAG],
    async () => graphqlContentRepository.getEditionItem(options),
  );
}

export function listCachedPublishedEditions(
  options: ListPublishedEditionsOptions = {},
): Promise<PublishedEditionConnection> {
  const limit = options.limit ?? 0;
  const nextToken = options.nextToken ?? "";
  return withReaderCache(
    ["reader-published-editions", String(limit), nextToken],
    [ARCHIVE_CACHE_TAG, EDITIONS_CACHE_TAG],
    async () => graphqlContentRepository.listPublishedEditions(options),
  );
}

export function getCachedLatestPublishedEdition(): Promise<EditionRouteSummary | null> {
  return withReaderCache(
    ["reader-latest-published-edition"],
    [EDITIONS_CACHE_TAG, ARCHIVE_CACHE_TAG],
    async () => graphqlContentRepository.getLatestPublishedEdition(),
  );
}
