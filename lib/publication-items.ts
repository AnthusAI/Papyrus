import {
  type Article,
  type ArticleAsset,
  type ArticleImage,
  type ArticleImageAsset,
  getArticleImageAssets,
  getArticleText,
} from "./articles";

export type PublicationItemType = "article" | "brief" | "correction" | "promo" | "ad" | "sectionHeader";

export type ArticlePublicationItem = Article & {
  type: "article";
};

export type NonArticlePublicationItem = {
  type: Exclude<PublicationItemType, "article">;
  slug: string;
  section?: string;
  title: string;
  deck?: string;
  excerpt?: string;
  body?: string[];
  image?: ArticleImage;
  assets?: ArticleAsset[];
  href?: string;
  metadata?: Record<string, unknown>;
};

export type PublicationItem = ArticlePublicationItem | NonArticlePublicationItem;

export function articleToPublicationItem(article: Article): ArticlePublicationItem {
  return {
    ...cloneArticle(article),
    type: "article",
  };
}

export function publicationItemToArticle(item: PublicationItem): Article | undefined {
  if (item.type !== "article") return undefined;
  const { type: _type, ...article } = item;
  return cloneArticle(article);
}

export function getArticlePublicationItems(items: PublicationItem[]): ArticlePublicationItem[] {
  return items.filter((item): item is ArticlePublicationItem => item.type === "article");
}

export function getPublicationItemText(item: PublicationItem): string {
  if (item.type === "article") return getArticleText(item);
  return [item.title, item.deck, ...(item.body ?? [])].filter(Boolean).join("\n\n");
}

export function getPublicationItemImageAssets(item: PublicationItem): ArticleImageAsset[] {
  if (item.type === "article") return getArticleImageAssets(item);
  const explicitAssets = item.assets?.filter((asset): asset is ArticleImageAsset => asset.type === "image") ?? [];
  if (explicitAssets.length > 0) return explicitAssets;
  if (!item.image) return [];
  return [
    {
      ...item.image,
      id: `${item.slug}-primary-image`,
      type: "image",
      roles: ["feature"],
    },
  ];
}

export function clonePublicationItems(items: PublicationItem[]): PublicationItem[] {
  return items.map((item) => (item.type === "article" ? articleToPublicationItem(item) : cloneNonArticleItem(item)));
}

export function cloneArticle(article: Article): Article {
  return {
    ...article,
    image: {
      ...article.image,
      layout: cloneImageLayout(article.image.layout),
      themeVariants: cloneImageThemeVariants(article.image.themeVariants),
    },
    assets: article.assets?.map((asset) => ({
      ...asset,
      layout: cloneImageLayout(asset.layout),
      roles: asset.roles ? [...asset.roles] : undefined,
      themeVariants: cloneImageThemeVariants(asset.themeVariants),
    })),
    pullQuotes: article.pullQuotes ? [...article.pullQuotes] : undefined,
    body: [...article.body],
  };
}

function cloneNonArticleItem(item: NonArticlePublicationItem): NonArticlePublicationItem {
  return {
    ...item,
    image: item.image
      ? {
          ...item.image,
          layout: cloneImageLayout(item.image.layout),
          themeVariants: cloneImageThemeVariants(item.image.themeVariants),
        }
      : undefined,
    assets: item.assets?.map((asset) => ({
      ...asset,
      layout: cloneImageLayout(asset.layout),
      roles: asset.roles ? [...asset.roles] : undefined,
      themeVariants: cloneImageThemeVariants(asset.themeVariants),
    })),
    body: item.body ? [...item.body] : undefined,
    metadata: item.metadata ? { ...item.metadata } : undefined,
  };
}

function cloneImageLayout<T extends Article["image"]["layout"]>(layout: T): T {
  if (!layout) return undefined as T;
  return {
    ...layout,
    inlineFloat: layout.inlineFloat ? { ...layout.inlineFloat } : undefined,
    focalPoint: layout.focalPoint ? { ...layout.focalPoint } : undefined,
  } as T;
}

function cloneImageThemeVariants<T extends Article["image"]["themeVariants"]>(themeVariants: T): T {
  if (!themeVariants) return undefined as T;
  return {
    ...themeVariants,
    dark: themeVariants.dark ? { ...themeVariants.dark } : undefined,
  } as T;
}
