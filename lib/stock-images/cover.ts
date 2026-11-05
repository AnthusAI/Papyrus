import { Document, parseDocument } from "yaml";
import type { CoverImageRecord, StockCandidate } from "./types";

/**
 * Making a picked image the Story's cover, as text the editor already saves: the body's first figure (with the credit directly under it on
 * the article page, through the existing `::image{ credit="..." }`) and the front matter (`image` for cards and sharing, `coverImage` for the
 * structured record). Nothing here writes anywhere; the editor's own save creates the new Story version.
 *
 * Credits show on the article page only (Ryan, 2026-11-05): a card or index page draws the picture from `image` and never reads `coverImage`.
 */
export const COVER_IMAGE_KEY = "coverImage";
const NIGHT_KEYS = ["imageDark", "coverDark", "thumbnailDark"];
/** The other keys a listing reads for its picture, after `image`. They would hide the new `image` only if `image` were empty, but a stale one is cleared so nothing old resurfaces. */
const OTHER_CARD_KEYS = ["cover", "thumbnail"];
const IMAGE_LINE = /^[ \t]*::image\{(?<attrs>[^}]*)\}[ \t]*$/gm;

function attribute(value: string): string {
  return value.replace(/["{}\r\n]+/g, " ").replace(/\s+/g, " ").trim();
}

/** The credit shown under the image: creator, licence, source. Present for every third-party image, required by its licence or not. */
export function creditLine(candidate: Pick<StockCandidate, "creator" | "licence" | "sourceLabel">): string {
  return `Image: ${candidate.creator}, ${candidate.licence.name}, via ${candidate.sourceLabel}`;
}

export function coverRecord(candidate: StockCandidate, srcPath: string, pickedAt: string, pickedBy: string | null): CoverImageRecord {
  return {
    source: candidate.source, sourceLabel: candidate.sourceLabel, sourceUrl: candidate.sourceUrl, title: candidate.title, creator: candidate.creator,
    licence: candidate.licence.name, licenceUrl: candidate.licence.url, srcPath, pickedAt, pickedBy,
  };
}

export function coverDirective(srcPath: string, alt: string, credit: string): string {
  return `::image{src="${srcPath}" alt="${attribute(alt)}" credit="${attribute(credit)}"}`;
}

function sourceOf(attributes: string): string | null {
  return attributes.match(/\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)')/)?.slice(1).find((part) => part !== undefined) ?? null;
}

/**
 * The body with the cover figure in. A figure that is the previous stock cover (or the remote picture a Reference seeded) is replaced in
 * place; any other figure, such as a diagram, stays, and the cover goes above everything else.
 */
export function bodyWithCover(body: string, directive: string, replaceableSources: readonly string[]): string {
  const sources = new Set(replaceableSources.filter(Boolean));
  let replaced = false;
  const next = body.replace(IMAGE_LINE, (line, attrs: string) => {
    const src = sourceOf(attrs);
    if (replaced || src === null || !sources.has(src)) return line;
    replaced = true;
    return directive;
  });
  if (replaced) return next;
  return body.trim() === "" ? `${directive}\n` : `${directive}\n\n${body.replace(/^\n+/, "")}`;
}

/** The sources in the body that a new cover may replace: the earlier stock cover, and a seeded remote picture. */
export function replaceableCoverSources(frontMatterYaml: string): string[] {
  const document = parseDocument(frontMatterYaml || "");
  if (document.errors.length) return [];
  const found: string[] = [];
  const earlier = (document.getIn([COVER_IMAGE_KEY, "srcPath"]) as unknown);
  if (typeof earlier === "string") found.push(earlier);
  const seeded = (document.getIn(["seededImage", "url"]) as unknown);
  if (typeof seeded === "string") found.push(seeded);
  return found;
}

/** The front matter with the cover in: `image` set to the copy, the record stored, a Night counterpart of the earlier picture cleared. */
export function frontMatterWithCover(frontMatterYaml: string, record: CoverImageRecord): string {
  const document: Document = parseDocument(frontMatterYaml || "");
  if (document.errors.length) throw new Error("The front matter has an error, so the cover could not be recorded. Fix it, then pick again.");
  const contents = document.contents as unknown;
  if (contents === null || contents === undefined) document.contents = document.createNode({}) as never;
  document.set("image", `/${record.srcPath}`);
  for (const key of [...NIGHT_KEYS, ...OTHER_CARD_KEYS, "seededImage"]) document.delete(key);
  document.set(COVER_IMAGE_KEY, document.createNode(record));
  return String(document);
}

export function readCoverRecord(frontMatterYaml: string | null | undefined): CoverImageRecord | null {
  if (!frontMatterYaml?.trim()) return null;
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return null;
  const value = (document.get(COVER_IMAGE_KEY) as { toJSON?: () => unknown } | null)?.toJSON?.();
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const text = (key: string) => (typeof record[key] === "string" ? (record[key] as string) : "");
  if (!text("creator") || !text("licence") || !text("srcPath")) return null;
  return {
    source: text("source"), sourceLabel: text("sourceLabel"), sourceUrl: text("sourceUrl"), title: text("title"), creator: text("creator"),
    licence: text("licence"), licenceUrl: text("licenceUrl") || null, srcPath: text("srcPath"), pickedAt: text("pickedAt"), pickedBy: text("pickedBy") || null,
  };
}
