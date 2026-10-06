import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import {
  deriveMarkus,
  publishItem,
  saveItemDraft,
  unpublishItem,
  type ContentActionError,
} from "./content-actions-client";
import { createDemoArticlesBackend } from "./content-actions-demo";

export type ArticleStatus = "draft" | "published";
export type ArticleType = "article" | "page";

export const ARTICLE_TYPES: ArticleType[] = ["article", "page"];

export type NewsroomArticleRow = {
  id: string;
  type: string;
  slug: string;
  section: string | null;
  title: string;
  status: ArticleStatus;
  pending: boolean;
  updatedAt: string;
};

export type ArticleItemSummary = {
  id: string;
  lineageId?: string | null;
  type: string;
  slug: string;
  section?: string | null;
  title?: string | null;
  status: string;
  contentHash?: string | null;
  updatedAt?: string | null;
};

export type PublishedItemSummary = {
  id: string;
  itemLineageId?: string | null;
  sourceItemId?: string | null;
  metadata?: unknown;
};

export type NewsroomArticleEditorState = {
  id: string | null;
  type: string;
  section: string;
  slug: string;
  frontMatterYaml: string;
  bodyMarkus: string;
  contentHash: string | null;
  status: ArticleStatus;
  versionNumber: number | null;
  dirty: boolean;
};

export type EditableArticle = {
  id: string;
  type: string;
  section: string | null;
  slug: string;
  frontMatterYaml: string;
  bodyMarkus: string;
  contentHash: string | null;
  status: ArticleStatus;
  versionNumber: number | null;
  aliases: string[];
  everPublished: boolean;
};

export type ArticlesBackend = {
  actions: {
    deriveMarkus: typeof deriveMarkus;
    saveItemDraft: typeof saveItemDraft;
    publishItem: typeof publishItem;
    unpublishItem: typeof unpublishItem;
  };
  listRows: () => Promise<NewsroomArticleRow[]>;
  loadArticle: (id: string) => Promise<EditableArticle>;
};

export function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function suggestSlug(frontMatterYaml: string): string {
  for (const line of frontMatterYaml.split("\n")) {
    const match = /^title\s*:\s*(.*)$/.exec(line);
    if (!match) continue;
    let value = match[1].trim();
    if (value.length >= 2 && (value[0] === '"' || value[0] === "'") && value.endsWith(value[0])) {
      value = value.slice(1, -1);
    }
    return slugify(value);
  }
  return "";
}

export function errorLine(errors: ContentActionError[]): number | null {
  for (const error of errors) {
    if (typeof error.line === "number") return error.line;
  }
  return null;
}

export function sourceLineOffset(frontMatterYaml: string | null): number {
  const yamlText = (frontMatterYaml ?? "").replace(/^\n+|\n+$/g, "");
  if (!yamlText.trim()) return 0;
  return yamlText.split("\n").length + 2;
}

export type ErrorLocation = { field: "frontMatterYaml" | "bodyMarkus"; line: number | null };

export function locateError(error: ContentActionError, frontMatterYaml: string | null): ErrorLocation {
  if (error.code === "front-matter") return { field: "frontMatterYaml", line: null };
  if (error.line === null) return { field: "bodyMarkus", line: null };
  const bodyLine = error.line - sourceLineOffset(frontMatterYaml);
  if (bodyLine >= 1) return { field: "bodyMarkus", line: bodyLine };
  return { field: "frontMatterYaml", line: Math.max(error.line - 1, 1) };
}

export function emptyArticle(): NewsroomArticleEditorState {
  return {
    id: null,
    type: "article",
    section: "",
    slug: "",
    frontMatterYaml: "title: \n",
    bodyMarkus: "",
    contentHash: null,
    status: "draft",
    versionNumber: null,
    dirty: false,
  };
}

function parseJsonObject(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function hasPendingChanges(item: ArticleItemSummary, published: PublishedItemSummary | null): boolean {
  if (!published) return false;
  return item.contentHash !== parseJsonObject(published.metadata).sourceContentHash;
}

export function articleStatusLabel(item: ArticleItemSummary, published: PublishedItemSummary | null): string {
  if (item.status !== "published") return "Draft";
  return hasPendingChanges(item, published) ? "Published, unpublished changes" : "Published";
}

function rowFromItem(item: ArticleItemSummary, published: PublishedItemSummary | null): NewsroomArticleRow {
  const status: ArticleStatus = item.status === "published" ? "published" : "draft";
  return {
    id: item.id,
    type: item.type,
    slug: item.slug,
    section: item.section ?? null,
    title: item.title || item.slug,
    status,
    pending: status === "published" && hasPendingChanges(item, published),
    updatedAt: item.updatedAt ?? "",
  };
}

export function sortRowsByUpdatedAtDescending(rows: NewsroomArticleRow[]): NewsroomArticleRow[] {
  return [...rows].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

export function rowStatusLabel(row: NewsroomArticleRow): string {
  if (row.status === "draft") return "Draft";
  return row.pending ? "Published, unpublished changes" : "Published";
}

type ListPage<T> = { data?: (T | null)[] | null; nextToken?: string | null; errors?: { message?: string }[] | null };
type ListOptions = { authMode: "userPool"; nextToken?: string | null; limit?: number };

export type ArticlesDataClient = {
  models: {
    Item: {
      listItemsByTypeStatusAndPublishedAt: (
        input: { typeStatus: string },
        options: ListOptions,
      ) => Promise<ListPage<ArticleItemSummary>>;
      get: (
        input: { id: string },
        options: { authMode: "userPool" },
      ) => Promise<{ data?: Record<string, unknown> | null; errors?: { message?: string }[] | null }>;
    };
    PublishedItem: {
      listPublishedItemsByTypeStatusAndPublishedAt: (
        input: { typeStatus: string },
        options: ListOptions,
      ) => Promise<ListPage<PublishedItemSummary>>;
    };
  };
};

const NEWSROOM_ARTICLE_TYPE_STATUSES = ["article#draft", "article#published", "page#draft", "page#published"];
const NEWSROOM_PUBLISHED_TYPE_STATUSES = ["article#published", "page#published"];

async function collectPages<T>(
  fetchPage: (options: ListOptions) => Promise<ListPage<T>>,
): Promise<T[]> {
  const collected: T[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const page: ListPage<T> = await fetchPage({ authMode: "userPool", nextToken, limit: 500 });
    if (page.errors && page.errors.length > 0) {
      throw new Error(page.errors.map((error) => error.message ?? "GraphQL error").join("; "));
    }
    for (const row of page.data ?? []) {
      if (row) collected.push(row);
    }
    nextToken = page.nextToken;
  } while (nextToken);
  return collected;
}

export async function loadArticleRows(client: ArticlesDataClient): Promise<NewsroomArticleRow[]> {
  const itemGroups = await Promise.all(
    NEWSROOM_ARTICLE_TYPE_STATUSES.map((typeStatus) =>
      collectPages((options) => client.models.Item.listItemsByTypeStatusAndPublishedAt({ typeStatus }, options)),
    ),
  );
  const publishedGroups = await Promise.all(
    NEWSROOM_PUBLISHED_TYPE_STATUSES.map((typeStatus) =>
      collectPages((options) =>
        client.models.PublishedItem.listPublishedItemsByTypeStatusAndPublishedAt({ typeStatus }, options),
      ),
    ),
  );
  const publishedByLineage = new Map<string, PublishedItemSummary>();
  for (const published of publishedGroups.flat()) {
    const lineage = published.itemLineageId ?? published.sourceItemId;
    if (lineage) publishedByLineage.set(lineage, published);
  }
  const rows = itemGroups
    .flat()
    .map((item) => rowFromItem(item, publishedByLineage.get(item.lineageId ?? item.id) ?? null));
  return sortRowsByUpdatedAtDescending(rows);
}

export async function loadEditableArticle(client: ArticlesDataClient, id: string): Promise<EditableArticle> {
  const response = await client.models.Item.get({ id }, { authMode: "userPool" });
  if (response.errors && response.errors.length > 0) {
    throw new Error(response.errors.map((error) => error.message ?? "GraphQL error").join("; "));
  }
  const record = response.data;
  if (!record) throw new Error("That article was not found.");
  const metadata = parseJsonObject(record.metadata);
  const status: ArticleStatus = record.status === "published" ? "published" : "draft";
  return {
    id: String(record.id),
    type: String(record.type),
    section: typeof record.section === "string" ? record.section : null,
    slug: String(record.slug),
    frontMatterYaml: typeof metadata.frontMatterYaml === "string" ? metadata.frontMatterYaml : "",
    bodyMarkus: typeof record.bodyMarkus === "string" ? record.bodyMarkus : "",
    contentHash: typeof record.contentHash === "string" ? record.contentHash : null,
    status,
    versionNumber: typeof record.versionNumber === "number" ? record.versionNumber : null,
    aliases: Array.isArray(record.aliases) ? record.aliases.map(String) : [],
    everPublished: status === "published",
  };
}

export function createLiveArticlesBackend(): ArticlesBackend {
  let client: ArticlesDataClient | null = null;
  const dataClient = () => {
    if (!client) client = generateClient<Schema>() as unknown as ArticlesDataClient;
    return client;
  };
  return {
    actions: { deriveMarkus, saveItemDraft, publishItem, unpublishItem },
    listRows: () => loadArticleRows(dataClient()),
    loadArticle: (id) => loadEditableArticle(dataClient(), id),
  };
}

let liveBackend: ArticlesBackend | null = null;
let demoBackend: ArticlesBackend | null = null;

export function resolveArticlesBackend(demo: boolean): ArticlesBackend {
  if (demo) {
    demoBackend ??= createDemoArticlesBackend();
    return demoBackend;
  }
  liveBackend ??= createLiveArticlesBackend();
  return liveBackend;
}

export function stagingPreviewUrl(
  stagingBaseUrl: string | undefined,
  type: string,
  slug: string,
  staticSite: boolean,
): string | null {
  if (!stagingBaseUrl || !slug || type !== "article") return null;
  const base = stagingBaseUrl.replace(/\/+$/, "");
  return staticSite ? `${base}/articles/${slug}.html` : `${base}/articles/${slug}`;
}

export function uniqueSections(rows: NewsroomArticleRow[]): string[] {
  const sections = new Set<string>();
  for (const row of rows) {
    if (row.section) sections.add(row.section);
  }
  return [...sections].sort();
}
