import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import type { Article, ArticleImage, ArticleImageAsset, ArticleImageLayout, ArticleImageThemeVariants, ArticleVideoAsset, ArticleVideoThemeVariants } from "./articles";
import { withContentLoadTiming } from "./content-load-timing";
import { getAmplifyServerRuntime } from "./amplify-server-runtime";
import { resolveReaderStorageUrl, signStorageUrl } from "./reader-storage-url";
import type { ContentRepository, EditionContent, EditionRouteSummary, ListPublishedEditionsOptions, LoadEditionContentOptions } from "./content-types";
import { isDemoAmplifyOutputs } from "./demo-amplify-outputs";
import { createEditionSectionPlan } from "./edition-sections";
import { normalizeEditionLayoutPlan, validateEditionLayoutPlanForItems, type EditionLayoutPlan } from "./layout-plan";
import {
  articleToPublicationItem,
  publicationItemToArticle,
  type NonArticlePublicationItem,
  type PublicationItem,
  type PublicationItemType,
} from "./publication-items";
import { BodyIrError, matchBodyImages, projectBodyIr, type BodyProjection, type BodyProjectionImage } from "./markus-body";
import { SITE_BRAND } from "./site-brand";
import { currentContentSource, runWithContentSource } from "./content-source-context";
import { getContentSource } from "./site-env";

const DEFAULT_EDITION_SLUG = "current";
const PUBLISHED_STATUS = "published";
const DRAFT_STATUS = "draft";
const ARTICLE_TYPE = "article";

type DataClient = ReturnType<typeof generateClient<Schema>>;
type EditionPublishedAtIndexQuery = (
  input: { status: string },
  options: Record<string, unknown>,
) => Promise<GraphQLListResponse<GraphQLEdition>>;

type GraphQLListResponse<T> = {
  data?: T[] | null;
  nextToken?: string | null;
  errors?: unknown[] | null;
};

type GraphQLGetResponse<T> = {
  data?: T | null;
  errors?: unknown[] | null;
};

type GraphQLEdition = {
  id: string;
  sourceEditionId?: string | null;
  editionLineageId?: string | null;
  versionNumber?: number | null;
  slug: string;
  title: string;
  status: string;
  editionDate: string;
  publishedAt?: string | null;
  description?: string | null;
  layoutPlan?: unknown;
  metadata?: unknown;
};

type GraphQLEditionItem = {
  id: string;
  publishedEditionId: string;
  publishedItemId: string;
  sortKey: string;
};

type GraphQLItem = {
  id: string;
  versionNumber?: number | null;
  type: string;
  status: string;
  slug: string;
  shortSlug?: string | null;
  section?: string | null;
  title?: string | null;
  headline?: string | null;
  deck?: string | null;
  bodyMarkus?: string | null;
  bodyIr?: unknown;
  aliases?: Array<string | null> | null;
  metadata?: unknown;
  byline?: string | null;
  dateline?: string | null;
  publishedAt?: string | null;
  pullQuotes?: Array<string | null> | null;
  editorial?: unknown;
};

type GraphQLMediaAsset = {
  id: string;
  publishedItemId: string;
  sourceItemId?: string | null;
  itemLineageId?: string | null;
  type: string;
  role: string;
  sortKey: string;
  storagePath?: string | null;
  externalUrl?: string | null;
  alt?: string | null;
  caption?: string | null;
  credit?: string | null;
  width?: number | null;
  height?: number | null;
  aspectRatio?: number | null;
  focalX?: number | null;
  focalY?: number | null;
  minHeight?: number | null;
  preferredHeight?: number | null;
  maxHeight?: number | null;
  crop?: string | null;
  wrapsText?: boolean | null;
  metadata?: unknown;
};

type ContentAttachmentPointer = {
  storagePath?: string | null;
  mediaType?: string | null;
  role?: string | null;
};

type ResolvedItemContent = {
  excerpt: string | null;
};

const IMAGE_ROLES: NonNullable<ArticleImageAsset["roles"]> = [
  "lead",
  "continuation",
  "continuationInset",
  "feature",
  "thumbnail",
];

let readerContextClient: DataClient | null = null;
let buildTimeClient: DataClient | null = null;

function authMode(): "userPool" | "identityPool" {
  return currentContentSource() === "drafts" ? "userPool" : "identityPool";
}

function isVisibleItemStatus(status: string): boolean {
  if (status === PUBLISHED_STATUS) return true;
  return currentContentSource() === "drafts" && status === DRAFT_STATUS;
}

async function withReaderGraphQLContext<T>(operation: () => Promise<T>): Promise<T> {
  const { runWithAmplifyServerContext } = getAmplifyServerRuntime();
  const source = getContentSource();
  const nextServerContext = source === "drafts" ? { cookies: (await import("next/headers")).cookies } : null;
  return runWithContentSource(source, () =>
    runWithAmplifyServerContext({
      nextServerContext,
      operation: async () => {
        readerContextClient = generateClient<Schema>({ authMode: authMode() });
        try {
          return await operation();
        } finally {
          readerContextClient = null;
        }
      },
    }),
  );
}

export const graphqlContentRepository: ContentRepository = {
  loadEditionContent(options) {
    return withReaderGraphQLContext(() =>
      withContentLoadTiming("loadEditionContent", { editionDate: options?.editionDate ?? null }, async () => {
        const edition = options?.editionDate
          ? await loadPublishedEditionForDate(options.editionDate, options.editionSlug)
          : await loadActiveEdition();
        return loadEditionContentFromEdition(edition);
      }),
    );
  },

  getLatestPublishedEdition() {
    if (isDemoAmplifyOutputs()) return null;
    return withReaderGraphQLContext(async () => {
      try {
        return summarizeEditionRoute(await loadLatestPublishedEdition());
      } catch (error) {
        if (isMissingReaderBackendError(error)) return null;
        throw error;
      }
    });
  },

  getFirstPublishedEdition() {
    if (isDemoAmplifyOutputs()) return null;
    return withReaderGraphQLContext(async () => {
      try {
        return summarizeEditionRoute(await loadFirstPublishedEdition());
      } catch (error) {
        if (isMissingReaderBackendError(error)) return null;
        throw error;
      }
    });
  },

  listPublishedEditions(options) {
    if (isDemoAmplifyOutputs()) {
      return { editions: [], nextToken: undefined };
    }
    return withReaderGraphQLContext(async () => {
      const result = await listPublishedEditionSummaries(options);
      return {
        editions: result.editions.map(summarizeEditionRoute),
        nextToken: result.nextToken,
      };
    });
  },

  getArticle(slug) {
    return withReaderGraphQLContext(async () => {
      const item = await getItemBySlug(slug);
      if (!item || item.type !== ARTICLE_TYPE || !isVisibleItemStatus(item.status)) return undefined;
      return normalizeArticle(item, await listMediaAssets(item.id));
    });
  },

  getEditionArticle({ editionDate, articleSlug }) {
    return withReaderGraphQLContext(async () => {
      const item = await loadEditionItem(editionDate, articleSlug);
      return item ? publicationItemToArticle(item) : undefined;
    });
  },

  getEditionItem({ editionDate, itemSlug }) {
    return withReaderGraphQLContext(() => loadEditionItem(editionDate, itemSlug));
  },

  listArticleSlugs() {
    return withReaderGraphQLContext(async () => {
      const items = await listItemsByTypeStatus(`${ARTICLE_TYPE}#${PUBLISHED_STATUS}`);
      return items
        .filter((item) => item.type === ARTICLE_TYPE && isVisibleItemStatus(item.status))
        .map((item) => item.slug)
        .sort();
    });
  },
};

function getClient(): DataClient {
  if (readerContextClient) return readerContextClient;

  if (!buildTimeClient) {
    getAmplifyServerRuntime();
    buildTimeClient = generateClient<Schema>({ authMode: authMode() });
  }
  return buildTimeClient;
}

async function loadActiveEdition(): Promise<GraphQLEdition> {
  const configuredSlug = process.env.PAPYRUS_EDITION_SLUG ?? DEFAULT_EDITION_SLUG;
  const bySlug = await listAll<GraphQLEdition>((options) =>
    getPublishedEditionModel().publishedEditionBySlug({ slug: configuredSlug }, options),
  );
  if (bySlug[0]) return bySlug[0];

  return loadLatestPublishedEdition();
}

async function loadLatestPublishedEdition(): Promise<GraphQLEdition> {
  const listByPublishedAt = getEditionPublishedAtIndexQuery();
  if (listByPublishedAt) {
    try {
      const [latestByPublishedAt] = await listFirst<GraphQLEdition>((options) =>
        listByPublishedAt({ status: PUBLISHED_STATUS }, options),
      );
      if (latestByPublishedAt) return latestByPublishedAt;
    } catch (error) {
      if (!isMissingPublishedAtIndexError(error)) throw error;
    }
  }

  const [latestByEditionDate] = await listFirst<GraphQLEdition>((options) =>
    getPublishedEditionModel().listPublishedEditionsByStatusAndEditionDate({ status: PUBLISHED_STATUS }, options),
  );
  if (latestByEditionDate) return latestByEditionDate;

  throw new Error("No published GraphQL edition found. Seed the Amplify sandbox or set PAPYRUS_EDITION_SLUG.");
}

async function loadFirstPublishedEdition(): Promise<GraphQLEdition> {
  const editions = await listAll<GraphQLEdition>((options) =>
    getPublishedEditionModel().listPublishedEditionsByStatusAndEditionDate({ status: PUBLISHED_STATUS }, options),
  );
  const [firstEdition] = editions.sort(compareEditionsByOldest);
  if (firstEdition) return firstEdition;
  throw new Error("No published GraphQL edition found. Seed the Amplify sandbox or set PAPYRUS_EDITION_SLUG.");
}

async function listPublishedEditionSummaries({
  limit = 12,
  nextToken,
}: ListPublishedEditionsOptions = {}): Promise<{ editions: GraphQLEdition[]; nextToken?: string | null }> {
  const safeLimit = clampEditionPageLimit(limit);
  const listByPublishedAt = getEditionPublishedAtIndexQuery();
  if (listByPublishedAt) {
    try {
      return await listPage<GraphQLEdition>(
        (options) => listByPublishedAt({ status: PUBLISHED_STATUS }, options),
        safeLimit,
        nextToken,
      );
    } catch (error) {
      if (!isMissingPublishedAtIndexError(error)) throw error;
    }
  }

  return listPage<GraphQLEdition>(
    (options) => getPublishedEditionModel().listPublishedEditionsByStatusAndEditionDate({ status: PUBLISHED_STATUS }, options),
    safeLimit,
    nextToken,
  );
}

async function loadPublishedEditionForDate(editionDate: string, editionSlug?: string | null): Promise<GraphQLEdition> {
  const editions = await listPublishedEditionsForDate(editionDate);
  const selectedEdition = editionSlug ? editions.find((edition) => edition.slug === editionSlug) : editions[0];
  if (!selectedEdition) {
    const slugDetail = editionSlug ? ` and slug ${editionSlug}` : "";
    throw new Error(`No published GraphQL edition found for date ${editionDate}${slugDetail}.`);
  }
  return selectedEdition;
}

async function listPublishedEditionsForDate(editionDate: string): Promise<GraphQLEdition[]> {
  const editions = await listAll<GraphQLEdition>((options) =>
    getPublishedEditionModel().listPublishedEditionsByStatusAndEditionDate(
      { status: PUBLISHED_STATUS, editionDate: { eq: editionDate } },
      options,
    ),
  );
  return editions.sort(compareEditionsByFreshness);
}

async function loadEditionContentFromEdition(edition: GraphQLEdition): Promise<EditionContent> {
  const layoutPlan = normalizeEditionLayoutPlan(edition.layoutPlan, "Edition.layoutPlan");
  const editionItems = await listEditionItems(edition.id);
  const editionMetadata = parseObjectMetadata(edition.metadata);
  const itemsBySlug = new Map<string, PublicationItem>();
  const normalizedEditionItems = (
    await Promise.all(
      editionItems.map(async (editionItem) => {
        const item = await getItemById(editionItem.publishedItemId);
        if (!item || !isVisibleItemStatus(item.status)) return null;
        return normalizePublicationItem(item, await listMediaAssets(item.id));
      }),
    )
  ).filter((item): item is PublicationItem => item !== null);
  for (const item of normalizedEditionItems) itemsBySlug.set(item.slug, item);

  const missingLayoutItems = [...collectLayoutPlanItemIds(layoutPlan)].filter((itemId) => !itemsBySlug.has(itemId));
  if (missingLayoutItems.length > 0) {
    const recoveredItems = (
      await Promise.all(
        missingLayoutItems.map(async (itemId) => {
          const item = await getItemBySlug(itemId);
          if (!item || !isVisibleItemStatus(item.status)) return null;
          return normalizePublicationItem(item, await listMediaAssets(item.id));
        }),
      )
    ).filter((item): item is PublicationItem => item !== null);
    for (const item of recoveredItems) itemsBySlug.set(item.slug, item);
  }

  const items = [...itemsBySlug.values()];
  const availableItemSlugs = new Set(items.map((item) => item.slug));
  const sanitizedLayoutPlan = pruneLayoutPlanUnavailableItems(layoutPlan, availableItemSlugs, edition.id);
  validateEditionLayoutPlanForItems(sanitizedLayoutPlan, items, `PublishedEdition(${edition.id}).layoutPlan`);

  return {
    id: edition.id,
    source: "graphql",
    title: edition.title,
    editionDate: edition.editionDate,
    description: edition.description ?? "GraphQL content loaded from Amplify Data.",
    layoutPlan: sanitizedLayoutPlan,
    items,
    sections: createEditionSectionPlan(items, edition.metadata),
    suppressNewsDeskAppendix: editionMetadata?.suppressNewsDeskAppendix === true,
    editionVideo: await normalizeEditionVideoAsset(editionMetadata?.editionVideo),
  };
}

async function normalizeEditionVideoAsset(value: unknown): Promise<ArticleVideoAsset | null> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const srcPath = typeof record.src === "string" ? record.src.trim() : "";
  if (!srcPath) return null;
  const storagePath = typeof record.storagePath === "string" ? record.storagePath.trim() : "";
  const src = storagePath ? await resolveReaderStorageUrl(storagePath) : srcPath;
  if (!src) return null;
  const posterSrc = typeof record.posterSrc === "string" && record.posterSrc.trim() ? record.posterSrc.trim() : undefined;
  const durationSeconds =
    typeof record.durationSeconds === "number" && Number.isFinite(record.durationSeconds)
      ? record.durationSeconds
      : undefined;
  const alt = typeof record.alt === "string" && record.alt.trim() ? record.alt.trim() : "Edition overview video";
  const caption = typeof record.caption === "string" ? record.caption.trim() : undefined;
  const credit = typeof record.credit === "string" && record.credit.trim() ? record.credit.trim() : (SITE_BRAND.defaultVideoCredit ?? "Edition overview video");
  const themeVariants = await parseVideoThemeVariantsMetadata(record.themeVariants);

  return {
    type: "video",
    src,
    posterSrc,
    alt,
    caption: caption || undefined,
    credit,
    durationSeconds,
    roles: ["feature"],
    themeVariants,
  };
}

function pruneLayoutPlanUnavailableItems(
  layoutPlan: EditionLayoutPlan,
  availableItemSlugs: Set<string>,
  editionId: string,
): EditionLayoutPlan {
  let removedBlocks = 0;
  const pages = layoutPlan.pages.map((page) => ({
    ...page,
    regions: page.regions.map((region) => ({
      ...region,
      blocks: region.blocks.filter((block) => {
        if ("itemId" in block && typeof block.itemId === "string" && block.itemId.trim()) {
          if (!availableItemSlugs.has(block.itemId)) {
            removedBlocks += 1;
            return false;
          }
        }
        if ("itemIds" in block && Array.isArray(block.itemIds)) {
          for (const itemId of block.itemIds) {
            if (typeof itemId === "string" && itemId.trim() && !availableItemSlugs.has(itemId)) {
              removedBlocks += 1;
              return false;
            }
          }
        }
        return true;
      }),
    })),
  }));
  if (removedBlocks > 0) {
    console.warn(
      `[graphql-content-repository] Pruned ${removedBlocks} layout block(s) that referenced unavailable published items in edition ${editionId}.`,
    );
  }
  return { ...layoutPlan, pages };
}

function collectLayoutPlanItemIds(layoutPlan: EditionLayoutPlan): Set<string> {
  const ids = new Set<string>();
  for (const page of layoutPlan.pages) {
    for (const region of page.regions) {
      for (const block of region.blocks) {
        if ("itemId" in block && typeof block.itemId === "string" && block.itemId.trim()) ids.add(block.itemId);
        if ("itemIds" in block && Array.isArray(block.itemIds)) {
          for (const itemId of block.itemIds) {
            if (typeof itemId === "string" && itemId.trim()) ids.add(itemId);
          }
        }
      }
    }
  }
  return ids;
}

async function loadEditionItem(editionDate: string, itemSlug: string): Promise<PublicationItem | undefined> {
  const edition = await loadPublishedEditionForDate(editionDate);
  const editionItems = await listEditionItems(edition.id);
  for (const editionItem of editionItems) {
    const item = await getItemById(editionItem.publishedItemId);
    if (!item || item.slug !== itemSlug || !isVisibleItemStatus(item.status)) continue;
    return (await normalizePublicationItem(item, await listMediaAssets(item.id))) ?? undefined;
  }
  return undefined;
}

function summarizeEditionRoute(edition: GraphQLEdition): EditionRouteSummary {
  return {
    id: edition.id,
    slug: edition.slug,
    title: edition.title,
    editionDate: edition.editionDate,
    publishedAt: edition.publishedAt,
    description: edition.description ?? null,
  };
}

function compareEditionsByFreshness(left: GraphQLEdition, right: GraphQLEdition): number {
  const leftPublishedAt = left.publishedAt ?? `${left.editionDate}T00:00:00.000Z`;
  const rightPublishedAt = right.publishedAt ?? `${right.editionDate}T00:00:00.000Z`;
  return rightPublishedAt.localeCompare(leftPublishedAt) || right.id.localeCompare(left.id);
}

function compareEditionsByOldest(left: GraphQLEdition, right: GraphQLEdition): number {
  const leftPublishedAt = left.publishedAt ?? `${left.editionDate}T00:00:00.000Z`;
  const rightPublishedAt = right.publishedAt ?? `${right.editionDate}T00:00:00.000Z`;
  return left.editionDate.localeCompare(right.editionDate)
    || leftPublishedAt.localeCompare(rightPublishedAt)
    || left.id.localeCompare(right.id);
}

function isMissingGraphQLEditionError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("No published GraphQL edition found");
}

function isMissingProjectionModelError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("missing projection model");
}

function isMissingReaderBackendError(error: unknown): boolean {
  return isMissingGraphQLEditionError(error) || isMissingProjectionModelError(error);
}

function getEditionPublishedAtIndexQuery(): EditionPublishedAtIndexQuery | null {
  const editionModel = getPublishedEditionModel();
  return typeof editionModel.listPublishedEditionsByStatusAndPublishedAt === "function"
    ? editionModel.listPublishedEditionsByStatusAndPublishedAt
    : null;
}

type ListOptions = Record<string, unknown>;
type ListResponse<T> = Promise<GraphQLListResponse<T>>;

type EditionSourceModel = {
  publishedEditionBySlug: (input: { slug: string }, options: ListOptions) => ListResponse<GraphQLEdition>;
  listPublishedEditionsByStatusAndEditionDate: (
    input: { status: string; editionDate?: { eq: string } },
    options: ListOptions,
  ) => ListResponse<GraphQLEdition>;
  listPublishedEditionsByStatusAndPublishedAt?: EditionPublishedAtIndexQuery;
};

type EditionItemSourceModel = {
  listPublishedEditionItemsByEditionAndSortKey: (
    input: { publishedEditionId: string },
    options: ListOptions,
  ) => ListResponse<GraphQLEditionItem>;
};

type ItemSourceModel = {
  get: (input: { id: string }, options: ListOptions) => Promise<GraphQLGetResponse<GraphQLItem>>;
  publishedItemBySlug: (input: { slug: string }, options: ListOptions) => ListResponse<GraphQLItem>;
  listPublishedItemsByTypeStatusAndPublishedAt: (input: { typeStatus: string }, options: ListOptions) => ListResponse<GraphQLItem>;
};

type MediaAssetSourceModel = {
  listPublishedMediaAssetsByItemAndSortKey: (
    input: { publishedItemId: string },
    options: ListOptions,
  ) => ListResponse<GraphQLMediaAsset>;
};

const DRAFTS_EDITION_STATUSES = [PUBLISHED_STATUS, DRAFT_STATUS];

async function listMergedAcrossStatuses<T>(
  statuses: string[],
  runForStatus: (status: string, pageOptions: ListOptions) => ListResponse<T>,
  sortValue: (row: T) => string,
  options: ListOptions,
): ListResponse<T> {
  const rows: T[] = [];
  for (const status of statuses) {
    let pageToken: string | null | undefined;
    do {
      const response = await runForStatus(status, { authMode: options.authMode, limit: 100, nextToken: pageToken });
      if (response.errors?.length) return { data: [], errors: response.errors };
      rows.push(...((response.data ?? []).filter(Boolean) as T[]));
      pageToken = response.nextToken;
    } while (pageToken);
  }
  const direction = options.sortDirection === "DESC" ? -1 : 1;
  rows.sort((left, right) => direction * sortValue(left).localeCompare(sortValue(right)));
  const offset = Number(options.nextToken ?? 0) || 0;
  const limit = typeof options.limit === "number" ? options.limit : undefined;
  const end = limit === undefined ? rows.length : offset + limit;
  return {
    data: rows.slice(offset, end),
    nextToken: end < rows.length ? String(end) : undefined,
  };
}

function getPublishedEditionModel(): EditionSourceModel {
  if (currentContentSource() === "drafts") {
    const model = getClient().models.Edition;
    if (!model) throw missingProjectionModelError("Edition");
    return {
      publishedEditionBySlug: (input, options) => model.editionBySlug(input, options) as ListResponse<GraphQLEdition>,
      listPublishedEditionsByStatusAndEditionDate: (input, options) =>
        listMergedAcrossStatuses<GraphQLEdition>(
          DRAFTS_EDITION_STATUSES,
          (status, pageOptions) =>
            model.listEditionsByStatusAndEditionDate({ ...input, status }, pageOptions) as ListResponse<GraphQLEdition>,
          (edition) => edition.editionDate,
          options,
        ),
    };
  }
  const model = getClient().models.PublishedEdition;
  if (!model) throw missingProjectionModelError("PublishedEdition");
  return model as unknown as EditionSourceModel;
}

function getPublishedEditionItemModel(): EditionItemSourceModel {
  if (currentContentSource() === "drafts") {
    const model = getClient().models.EditionItem;
    if (!model) throw missingProjectionModelError("EditionItem");
    return {
      listPublishedEditionItemsByEditionAndSortKey: async ({ publishedEditionId }, options) => {
        const response = (await model.listEditionItemsByEditionAndSortKey(
          { editionId: publishedEditionId },
          options,
        )) as unknown as GraphQLListResponse<{ id: string; editionId: string; itemId: string; sortKey: string }>;
        return {
          ...response,
          data: (response.data ?? []).filter(Boolean).map((row) => ({
            id: row.id,
            publishedEditionId: row.editionId,
            publishedItemId: row.itemId,
            sortKey: row.sortKey,
          })),
        };
      },
    };
  }
  const model = getClient().models.PublishedEditionItem;
  if (!model) throw missingProjectionModelError("PublishedEditionItem");
  return model as unknown as EditionItemSourceModel;
}

function getPublishedItemModel(): ItemSourceModel {
  if (currentContentSource() === "drafts") {
    const model = getClient().models.Item;
    if (!model) throw missingProjectionModelError("Item");
    return {
      get: (input, options) => model.get(input, options) as Promise<GraphQLGetResponse<GraphQLItem>>,
      publishedItemBySlug: (input, options) => model.itemBySlug(input, options) as ListResponse<GraphQLItem>,
      listPublishedItemsByTypeStatusAndPublishedAt: ({ typeStatus }, options) => {
        const itemType = typeStatus.split("#")[0];
        return listMergedAcrossStatuses<GraphQLItem>(
          [DRAFT_STATUS, PUBLISHED_STATUS],
          (status, pageOptions) =>
            model.listItemsByTypeStatusAndPublishedAt(
              { typeStatus: `${itemType}#${status}` },
              pageOptions,
            ) as ListResponse<GraphQLItem>,
          (item) => item.publishedAt ?? "",
          options,
        );
      },
    };
  }
  const model = getClient().models.PublishedItem;
  if (!model) throw missingProjectionModelError("PublishedItem");
  return model as unknown as ItemSourceModel;
}

function getPublishedMediaAssetModel(): MediaAssetSourceModel {
  if (currentContentSource() === "drafts") {
    const model = getClient().models.MediaAsset;
    if (!model) throw missingProjectionModelError("MediaAsset");
    return {
      listPublishedMediaAssetsByItemAndSortKey: async ({ publishedItemId }, options) => {
        const response = (await model.listMediaAssetsByItemAndSortKey(
          { itemId: publishedItemId },
          options,
        )) as unknown as GraphQLListResponse<Omit<GraphQLMediaAsset, "publishedItemId"> & { itemId: string }>;
        return {
          ...response,
          data: (response.data ?? []).filter(Boolean).map((row) => ({ ...row, publishedItemId: row.itemId })),
        };
      },
    };
  }
  const model = getClient().models.PublishedMediaAsset;
  if (!model) throw missingProjectionModelError("PublishedMediaAsset");
  return model as unknown as MediaAssetSourceModel;
}

function missingProjectionModelError(modelName: string): Error {
  return new Error(
    `Amplify output is missing projection model ${modelName}. Refresh amplify_outputs.json from the latest deployed backend or regenerate it from the current sandbox schema.`,
  );
}

function isMissingPublishedAtIndexError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("listPublishedEditionsByStatusAndPublishedAt");
}

async function listEditionItems(editionId: string): Promise<GraphQLEditionItem[]> {
  const items = await listAll<GraphQLEditionItem>((options) =>
    getPublishedEditionItemModel().listPublishedEditionItemsByEditionAndSortKey({ publishedEditionId: editionId }, options),
  );
  return items.sort((left, right) => left.sortKey.localeCompare(right.sortKey));
}

async function listItemsByTypeStatus(typeStatus: string): Promise<GraphQLItem[]> {
  return listAll<GraphQLItem>((options) =>
    getPublishedItemModel().listPublishedItemsByTypeStatusAndPublishedAt({ typeStatus }, options),
  );
}

async function getItemById(id: string): Promise<GraphQLItem | null> {
  const response = await getPublishedItemModel().get({ id }, { authMode: authMode() });
  return readGetResponse<GraphQLItem>(response);
}

async function getItemBySlug(slug: string): Promise<GraphQLItem | null> {
  const items = await listAll<GraphQLItem>((options) => getPublishedItemModel().publishedItemBySlug({ slug }, options));
  return items[0] ?? null;
}

async function listMediaAssets(itemId: string): Promise<GraphQLMediaAsset[]> {
  const mediaAssets = await listAll<GraphQLMediaAsset>((options) =>
    getPublishedMediaAssetModel().listPublishedMediaAssetsByItemAndSortKey({ publishedItemId: itemId }, options),
  );
  return mediaAssets.sort((left, right) => left.sortKey.localeCompare(right.sortKey));
}

async function listAll<T>(operation: (options: Record<string, unknown>) => Promise<GraphQLListResponse<T>>): Promise<T[]> {
  const items: T[] = [];
  let nextToken: string | null | undefined;

  do {
    const response = await operation({
      authMode: authMode(),
      limit: 100,
      nextToken,
    });
    assertNoGraphQLErrors(response.errors);
    items.push(...((response.data ?? []).filter(Boolean) as T[]));
    nextToken = response.nextToken;
  } while (nextToken);

  return items;
}

async function listFirst<T>(operation: (options: Record<string, unknown>) => Promise<GraphQLListResponse<T>>): Promise<T[]> {
  const response = await operation({
    authMode: authMode(),
    limit: 1,
    sortDirection: "DESC",
  });
  assertNoGraphQLErrors(response.errors);
  return (response.data ?? []).filter(Boolean) as T[];
}

async function listPage<T>(
  operation: (options: Record<string, unknown>) => Promise<GraphQLListResponse<T>>,
  limit: number,
  nextToken?: string | null,
): Promise<{ editions: T[]; nextToken?: string | null }> {
  const response = await operation({
    authMode: authMode(),
    limit,
    nextToken,
    sortDirection: "DESC",
  });
  assertNoGraphQLErrors(response.errors);
  return {
    editions: (response.data ?? []).filter(Boolean) as T[],
    nextToken: response.nextToken,
  };
}

function clampEditionPageLimit(limit: number): number {
  if (!Number.isFinite(limit)) return 12;
  return Math.max(1, Math.min(12, Math.floor(limit)));
}

function readGetResponse<T>(response: GraphQLGetResponse<T>): T | null {
  assertNoGraphQLErrors(response.errors);
  return response.data ?? null;
}

async function normalizeArticle(item: GraphQLItem, mediaAssets: GraphQLMediaAsset[]): Promise<Article> {
  const resolvedContent = await resolveItemContentFromAttachments(item.editorial);
  const bodyProjection = projectPublishedItemBody(item);
  const videoAssets = mediaAssets.filter((asset) => asset.type === "video");
  const assets = await normalizeItemImageAssets(item, mediaAssets, bodyProjection.imageSrcs);
  const primaryImage = assets.find((asset) => asset.roles?.includes("lead")) ?? assets[0];
  const normalizedVideos = (
    await Promise.all(videoAssets.map((asset) => normalizeVideoAsset(item, asset, primaryImage)))
  ).filter((asset): asset is ArticleVideoAsset => asset !== null);
  const leadVideo = normalizedVideos.find((asset) => asset.roles?.includes("lead")) ?? normalizedVideos[0];

  return {
    slug: item.slug,
    shortSlug: normalizeShortSlug(item.shortSlug),
    section: item.section ?? "News",
    headline: item.headline ?? item.title ?? item.slug,
    deck: item.deck ?? "",
    excerpt: resolvedContent.excerpt ?? undefined,
    byline: item.byline ?? SITE_BRAND.placeholderByline,
    dateline: item.dateline ?? "NEWSROOM",
    image: primaryImage,
    video: leadVideo,
    assets: [...assets, ...normalizedVideos],
    pullQuotes: bodyProjection.pullQuotes,
    body: bodyProjection.body,
  };
}

function projectPublishedItemBody(item: GraphQLItem): BodyProjection {
  if (item.bodyIr === null || item.bodyIr === undefined || item.bodyIr === "") {
    throw new BodyIrError(`PublishedItem ${item.slug} has no bodyIr; run: papyrus content convert-bodies`);
  }
  return projectBodyIr(item.bodyIr);
}

async function normalizeItemImageAssets(
  item: GraphQLItem,
  mediaAssets: GraphQLMediaAsset[],
  bodyImages: BodyProjectionImage[],
): Promise<ArticleImageAsset[]> {
  const imageAssets = mediaAssets.filter((asset) => asset.type === "image");
  const matches = matchBodyImages(
    bodyImages,
    imageAssets.map((asset) => {
      const srcPath = parseObjectMetadata(asset.metadata)?.srcPath;
      return typeof srcPath === "string" ? srcPath : null;
    }),
  );
  const normalizedMedia = (
    await Promise.all(imageAssets.map((asset) => normalizeImageAsset(item, asset)))
  ).filter((asset): asset is ArticleImageAsset => asset !== null);
  const externalImages = matches.flatMap((match, index): ArticleImageAsset[] =>
    match.kind === "external"
      ? [
          {
            id: `${item.id}-body-image-${index}`,
            type: "image",
            src: match.image.src,
            alt: match.image.alt,
            caption: match.image.caption,
            credit: match.image.credit ?? match.image.caption ?? "Media asset",
          },
        ]
      : [],
  );
  return [...normalizedMedia, ...externalImages];
}

async function normalizePublicationItem(item: GraphQLItem, mediaAssets: GraphQLMediaAsset[]): Promise<PublicationItem | null> {
  if (item.type === "article") return articleToPublicationItem(await normalizeArticle(item, mediaAssets));
  const type = normalizePublicationItemType(item.type);
  if (!type) return null;
  const resolvedContent = await resolveItemContentFromAttachments(item.editorial);
  const bodyProjection = projectPublishedItemBody(item);
  const videoAssets = mediaAssets.filter((asset) => asset.type === "video");
  const assets = await normalizeItemImageAssets(item, mediaAssets, bodyProjection.imageSrcs);
  const image = assets[0] ?? undefined;
  const normalizedVideos = (
    await Promise.all(videoAssets.map((asset) => normalizeVideoAsset(item, asset, image)))
  ).filter((asset): asset is ArticleVideoAsset => asset !== null);
  const video = normalizedVideos.find((asset) => asset.roles?.includes("lead")) ?? normalizedVideos[0];
  const publicationItem: NonArticlePublicationItem = {
    type,
    slug: item.slug,
    section: item.section ?? "News",
    title: item.headline ?? item.title ?? item.slug,
    deck: item.deck ?? undefined,
    excerpt: resolvedContent.excerpt ?? undefined,
    body: bodyProjection.body,
    image,
    video,
    assets: [...assets, ...normalizedVideos],
  };
  return publicationItem;
}

async function resolveItemContentFromAttachments(editorial: unknown): Promise<ResolvedItemContent> {
  const pointers = parseContentAttachmentPointers(editorial);
  const excerptText = await readAttachmentPointerText(pointers.excerpt);
  return {
    excerpt: excerptText?.trim() || readInlineExcerpt(editorial) || null,
  };
}

async function readAttachmentPointerText(pointer: ContentAttachmentPointer | null): Promise<string | null> {
  const storagePath = typeof pointer?.storagePath === "string" ? pointer.storagePath.trim() : "";
  if (!storagePath) return null;
  try {
    const signedUrl = await signStorageUrl(storagePath);
    const response = await fetch(signedUrl);
    if (!response.ok) return null;
    const text = await response.text();
    return text.trim() ? text : null;
  } catch {
    return null;
  }
}

function parseContentAttachmentPointers(editorial: unknown): { excerpt: ContentAttachmentPointer | null } {
  const parsed = parseObjectMetadata(editorial);
  const attachments = readContentAttachmentObject(parsed);
  return {
    excerpt: parseAttachmentPointer(attachments?.excerpt),
  };
}

function readContentAttachmentObject(
  editorial: Record<string, unknown> | undefined,
): Record<string, unknown> | null {
  if (!editorial) return null;
  if (editorial.contentAttachments && typeof editorial.contentAttachments === "object" && !Array.isArray(editorial.contentAttachments)) {
    return editorial.contentAttachments as Record<string, unknown>;
  }
  const newsroom = editorial.newsroom;
  if (!newsroom || typeof newsroom !== "object" || Array.isArray(newsroom)) return null;
  const nested = (newsroom as Record<string, unknown>).contentAttachments;
  if (!nested || typeof nested !== "object" || Array.isArray(nested)) return null;
  return nested as Record<string, unknown>;
}

function parseAttachmentPointer(value: unknown): ContentAttachmentPointer | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const storagePath = typeof record.storagePath === "string" ? record.storagePath.trim() : "";
  if (!storagePath) return null;
  return {
    storagePath,
    mediaType: typeof record.mediaType === "string" ? record.mediaType : null,
    role: typeof record.role === "string" ? record.role : null,
  };
}

function readInlineExcerpt(editorial: unknown): string | null {
  const parsed = parseObjectMetadata(editorial);
  if (!parsed) return null;
  const direct = parsed.excerpt;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const newsroom = parsed.newsroom;
  if (!newsroom || typeof newsroom !== "object" || Array.isArray(newsroom)) return null;
  const nestedExcerpt = (newsroom as Record<string, unknown>).excerpt;
  return typeof nestedExcerpt === "string" && nestedExcerpt.trim() ? nestedExcerpt.trim() : null;
}

function normalizePublicationItemType(value: string): Exclude<PublicationItemType, "article"> | null {
  if (value === "brief" || value === "correction" || value === "promo" || value === "ad" || value === "sectionHeader") return value;
  return null;
}

async function normalizeImageAsset(item: GraphQLItem, asset: GraphQLMediaAsset): Promise<ArticleImageAsset | null> {
  const metadata = parseObjectMetadata(asset.metadata);
  const pictogramSlug = typeof metadata?.pictogramSlug === "string" ? metadata.pictogramSlug.trim() : "";
  const src = await getMediaUrl(asset);
  if (!src && !pictogramSlug) return null;
  const themeVariants = await parseThemeVariantsMetadata(metadata?.themeVariants);

  return {
    id: asset.id,
    type: "image",
    src: src ?? "",
    alt: asset.alt ?? `Image for ${item.headline ?? item.slug}`,
    caption: asset.caption ?? undefined,
    credit: asset.credit ?? asset.caption ?? "Media asset",
    roles: parseImageRoles(asset.role),
    layout: getImageLayout(asset, metadata),
    themeVariants,
  };
}

async function normalizeVideoAsset(
  item: GraphQLItem,
  asset: GraphQLMediaAsset,
  fallbackPoster?: ArticleImage,
): Promise<ArticleVideoAsset | null> {
  const src = await getMediaUrl(asset);
  if (!src) return null;
  const metadata = parseObjectMetadata(asset.metadata);
  const posterFromMetadata = typeof metadata?.posterSrc === "string" ? metadata.posterSrc.trim() : "";
  const posterSrc = posterFromMetadata || fallbackPoster?.src || undefined;
  const durationSeconds =
    typeof metadata?.durationSeconds === "number" && Number.isFinite(metadata.durationSeconds)
      ? metadata.durationSeconds
      : undefined;

  return {
    id: asset.id,
    type: "video",
    src,
    posterSrc,
    alt: asset.alt ?? `Video for ${item.headline ?? item.slug}`,
    caption: asset.caption ?? undefined,
    credit: asset.credit ?? asset.caption ?? "Media asset",
    durationSeconds,
    roles: parseVideoRoles(asset.role),
    themeVariants: await parseVideoThemeVariantsMetadata(metadata?.themeVariants),
  };
}

function parseVideoRoles(role: string | null | undefined): ArticleVideoAsset["roles"] {
  const parsed = parseImageRoles(role);
  if (!parsed?.length) return ["lead"];
  return parsed.filter((entry): entry is NonNullable<ArticleVideoAsset["roles"]>[number] =>
    entry === "lead" || entry === "feature" || entry === "thumbnail",
  );
}

async function getMediaUrl(asset: GraphQLMediaAsset): Promise<string | null> {
  if (asset.storagePath) return resolveReaderStorageUrl(asset.storagePath);
  return asset.externalUrl ?? null;
}

function getImageLayout(asset: GraphQLMediaAsset, metadata?: Record<string, unknown>): ArticleImageLayout | undefined {
  const aspectRatio = asset.aspectRatio ?? (asset.width && asset.height ? asset.width / asset.height : null);
  if (!aspectRatio) return undefined;

  return {
    minHeight: asset.minHeight ?? 110,
    preferredHeight: asset.preferredHeight ?? Math.round(220 / aspectRatio),
    maxHeight: asset.maxHeight ?? 440,
    aspectRatio,
    crop: asset.crop === "contain" ? "contain" : "cover",
    wrapsText: asset.wrapsText ?? true,
    inlineFloat: parseInlineFloatMetadata(metadata?.inlineFloat),
    focalPoint:
      typeof asset.focalX === "number" && typeof asset.focalY === "number"
        ? {
            x: asset.focalX,
            y: asset.focalY,
          }
        : undefined,
  };
}

async function parseThemeVariantsMetadata(value: unknown): Promise<ArticleImageThemeVariants | undefined> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const variants = value as Record<string, unknown>;
  const dark = await resolveThemeVariantSource(variants.dark);
  if (!dark) return undefined;
  return { dark: { src: dark } };
}

async function parseVideoThemeVariantsMetadata(value: unknown): Promise<ArticleVideoThemeVariants | undefined> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const variants = value as Record<string, unknown>;
  const [light, dark] = await Promise.all([
    resolveThemeVariantSource(variants.light),
    resolveThemeVariantSource(variants.dark),
  ]);
  if (!light && !dark) return undefined;
  return {
    ...(light ? { light: { src: light } } : {}),
    ...(dark ? { dark: { src: dark } } : {}),
  };
}

async function resolveThemeVariantSource(value: unknown): Promise<string | undefined> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const entry = value as Record<string, unknown>;
  const storagePath = typeof entry.storagePath === "string" && entry.storagePath.trim() ? entry.storagePath.trim() : null;
  if (storagePath) return resolveReaderStorageUrl(storagePath);
  const sourceUrl = typeof entry.sourceUrl === "string" && entry.sourceUrl.trim() ? entry.sourceUrl.trim() : null;
  if (sourceUrl) return sourceUrl;
  const src = typeof entry.src === "string" && entry.src.trim() ? entry.src.trim() : null;
  return src ?? undefined;
}

function parseObjectMetadata(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return undefined;
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : undefined;
  } catch {
    return undefined;
  }
}

function parseInlineFloatMetadata(value: unknown): ArticleImageLayout["inlineFloat"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  return {
    minColumnCount: optionalPositiveNumber(record.minColumnCount),
    columnSpan: optionalPositiveNumber(record.columnSpan),
    widthRatio: optionalPositiveNumber(record.widthRatio),
    narrowWidthRatio: optionalPositiveNumber(record.narrowWidthRatio),
    maxWidthRatio: optionalPositiveNumber(record.maxWidthRatio),
    minWidth: optionalPositiveNumber(record.minWidth),
  };
}

function optionalPositiveNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

function getFallbackImage(item: GraphQLItem): ArticleImage {
  return {
    src: "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=1200&q=80",
    alt: `Editorial image for ${item.headline ?? item.slug}`,
    caption: "Fallback editorial image.",
    credit: "Fallback image",
    layout: {
      minHeight: 120,
      preferredHeight: 220,
      maxHeight: 420,
      aspectRatio: 1.5,
      crop: "cover",
      wrapsText: true,
    },
  };
}

function parseImageRoles(role: string | null | undefined): ArticleImageAsset["roles"] {
  const roles = (role ?? "")
    .split(/[,\s]+/)
    .map((candidate) => candidate.trim())
    .filter((candidate): candidate is NonNullable<ArticleImageAsset["roles"]>[number] =>
      IMAGE_ROLES.includes(candidate as NonNullable<ArticleImageAsset["roles"]>[number]),
    );
  return roles.length > 0 ? roles : ["lead", "continuation", "continuationInset"];
}

function normalizeShortSlug(value: string | null | undefined): string | undefined {
  const shortSlug = value?.trim().toUpperCase();
  return shortSlug || undefined;
}

function assertNoGraphQLErrors(errors: unknown[] | null | undefined): void {
  if (!errors?.length) return;
  throw new Error(`GraphQL content request failed: ${JSON.stringify(errors)}`);
}
