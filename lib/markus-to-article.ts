import path from "node:path";
import type { Article, ArticleImage, ArticleImageAsset } from "./articles";
import type { MarkusDocument } from "./markus-ir";
import { projectMarkusDocumentToPretext } from "./markus-projection";

export type MarkusToArticleOptions = {
  slug: string;
  /** Directory containing the source `.md` file; used to resolve relative figure paths. */
  markdownDir?: string;
  /** URL prefix for assets resolved from `web/content/assets/` (default `/pilobol-sample-assets`). */
  assetUrlPrefix?: string;
  section?: string;
};

function formatByline(authors: unknown): string {
  if (Array.isArray(authors)) {
    return authors.map((author) => String(author)).filter(Boolean).join(", ");
  }
  if (typeof authors === "string" && authors.trim().length > 0) return authors;
  return "Pilobol.us";
}

function formatDateline(date: unknown): string {
  if (typeof date !== "string" || date.trim().length === 0) return "";
  const parsed = new Date(`${date}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function resolveMarkusAssetSrc(
  src: string,
  markdownDir: string,
  assetUrlPrefix: string,
): string {
  if (/^https?:\/\//.test(src) || src.startsWith("/")) return src;
  const resolved = path.normalize(path.join(markdownDir, src));
  const filename = path.basename(resolved);
  return `${assetUrlPrefix.replace(/\/$/, "")}/${filename}`;
}

function toArticleImage(asset: ArticleImageAsset): ArticleImage {
  return {
    src: asset.src,
    alt: asset.alt,
    caption: asset.caption,
    credit: asset.credit,
  };
}

/**
 * Map a typed Markus document IR into the legacy `Article` shape the Pretext
 * solver consumes. Projection rules live in `lib/markus-projection.ts`.
 */
export function markusDocumentToArticle(
  document: MarkusDocument,
  options: MarkusToArticleOptions,
): Article {
  const projection = projectMarkusDocumentToPretext(document);
  const frontMatter = document.front_matter;
  const markdownDir = options.markdownDir ?? "";
  const assetUrlPrefix = options.assetUrlPrefix ?? "/pilobol-sample-assets";

  const assets = projection.images.map((asset) => ({
    ...asset,
    src: resolveMarkusAssetSrc(asset.src, markdownDir, assetUrlPrefix),
  }));

  const primaryAsset = assets[0];
  const headline =
    typeof frontMatter.title === "string" && frontMatter.title.trim().length > 0
      ? frontMatter.title
      : options.slug.replace(/-/g, " ");

  return {
    slug: options.slug,
    section:
      options.section ??
      (typeof frontMatter.section === "string" ? frontMatter.section : "Pilobol.us"),
    headline,
    deck: typeof frontMatter.deck === "string" ? frontMatter.deck : "",
    byline: formatByline(frontMatter.authors),
    dateline: formatDateline(frontMatter.date),
    body: projection.body,
    pullQuotes: projection.pullQuotes.length > 0 ? projection.pullQuotes : undefined,
    assets: assets.length > 0 ? assets : undefined,
    image: primaryAsset ? toArticleImage(primaryAsset) : undefined,
  };
}
