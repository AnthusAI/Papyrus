import type { Article, ArticleVideoAsset } from "./articles";
import type { EditionLayoutPlan } from "./layout-plan";
import type { PublicationItem } from "./publication-items";

export type ContentSource = "scenario" | "graphql";

export type EditionPresentationFormat = "newspaper" | "blog" | "magazine";

export type EditionSection = {
  key: string;
  label: string;
  description?: string | null;
  itemIds: string[];
};

export type NewsDeskCategoryTreeNode = {
  id: string;
  categorySetId: string;
  categoryKey: string;
  parentCategoryKey?: string | null;
  displayName: string;
  shortTitle?: string | null;
  subtitle?: string | null;
  description?: string | null;
  status: string;
  seedItemIds?: Array<string | null> | null;
  holdoutItemIds?: Array<string | null> | null;
  rank?: number | null;
  depth?: number | null;
};

export type NewsDeskAppendix = {
  categorySetId: string;
  corpusId: string;
  displayName: string;
  description?: string | null;
  generatedAt?: string | null;
  nodes: NewsDeskCategoryTreeNode[];
};

export type EditionContent = {
  id: string;
  source: ContentSource;
  title: string;
  editionDate: string;
  items: PublicationItem[];
  sections: EditionSection[];
  layoutPlan: EditionLayoutPlan;
  placeholderMode?: "emptyEdition";
  suppressNewsDeskAppendix?: boolean;
  defaultPresentation?: EditionPresentationFormat;
  presentationPlans?: Partial<Record<EditionPresentationFormat, unknown>>;
  newsDeskAppendix?: NewsDeskAppendix | null;
  scenarioId?: string;
  description?: string;
  editionVideo?: ArticleVideoAsset | null;
};

export type EditionRouteSummary = {
  id: string;
  slug: string;
  title: string;
  editionDate: string;
  publishedAt?: string | null;
  description?: string | null;
};

export type ListPublishedEditionsOptions = {
  limit?: number;
  nextToken?: string | null;
};

export type PublishedEditionConnection = {
  editions: EditionRouteSummary[];
  nextToken?: string | null;
};

export type LoadEditionContentOptions = {
  scenarioId?: string | null;
  editionDate?: string | null;
  editionSlug?: string | null;
};

export type GetEditionArticleOptions = {
  editionDate: string;
  articleSlug: string;
};

export type GetEditionItemOptions = {
  editionDate: string;
  itemSlug: string;
};

export type ContentRepository = {
  loadEditionContent(options?: LoadEditionContentOptions): EditionContent | Promise<EditionContent>;
  getLatestPublishedEdition(): EditionRouteSummary | null | Promise<EditionRouteSummary | null>;
  getFirstPublishedEdition(): EditionRouteSummary | null | Promise<EditionRouteSummary | null>;
  listPublishedEditions(options?: ListPublishedEditionsOptions): PublishedEditionConnection | Promise<PublishedEditionConnection>;
  getArticle(slug: string): Article | undefined | Promise<Article | undefined>;
  getEditionArticle(options: GetEditionArticleOptions): Article | undefined | Promise<Article | undefined>;
  getEditionItem(options: GetEditionItemOptions): PublicationItem | undefined | Promise<PublicationItem | undefined>;
  listArticleSlugs(): string[] | Promise<string[]>;
};
