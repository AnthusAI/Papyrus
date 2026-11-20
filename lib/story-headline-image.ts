import { parseDocument } from "yaml";
import type { MediaAssetRecord } from "./newsroom-media";

/** The keys a listing reads for a Story's picture, first match wins. Mirrors IMAGE_FIELDS in src/papyrus_content/projection/standard/entries.py. */
export const HEADLINE_IMAGE_KEYS = ["image", "cover", "ogImage", "thumbnail"] as const;

export type HeadlineImageRef = { key: string; value: string; remote: boolean; mediaPath: string | null; alt: string };

/**
 * Where the headline (card and sharing) picture is named in the version's front matter: the first of `image`, `cover`, `ogImage`, `thumbnail` with
 * text in it. A site-media picture is stored as `/<srcPath>` (the cover picker writes the leading slash), while the media rows and the preview's
 * address map are keyed by `<srcPath>`, so `mediaPath` is the value without the leading slash. A full address is remote and is shown as it is.
 */
export function readHeadlineImage(frontMatterYaml: string | null | undefined, bodyMarkus: string | null | undefined = ""): HeadlineImageRef | null {
  if (!frontMatterYaml?.trim()) return null;
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return null;
  for (const key of HEADLINE_IMAGE_KEYS) {
    const raw = document.get(key);
    const value = typeof raw === "string" ? raw.trim() : "";
    if (!value) continue;
    const remote = /^https?:\/\//i.test(value);
    const mediaPath = remote ? null : value.replace(/^\/+/, "").replace(/^media\//, "");
    return { key, value, remote, mediaPath, alt: altFor(document.toJSON() as Record<string, unknown>, bodyMarkus ?? "", remote ? value : mediaPath ?? value) };
  }
  return null;
}

/** The picture's alt text: the body figure that uses the same file, else the cover record's title, else the Story's title; empty only when none exists. */
function altFor(front: Record<string, unknown>, body: string, source: string): string {
  for (const line of body.split("\n")) {
    const match = /^\s*::image\{(.*)\}\s*$/.exec(line);
    if (!match) continue;
    const src = /\bsrc="([^"]*)"/.exec(match[1])?.[1]?.replace(/^\/+/, "");
    const alt = /\balt="([^"]*)"/.exec(match[1])?.[1]?.trim();
    if (src && alt && src === source.replace(/^\/+/, "")) return alt;
  }
  const cover = front.coverImage as { title?: unknown } | undefined;
  if (typeof cover?.title === "string" && cover.title.trim()) return cover.title.trim();
  return typeof front.title === "string" ? front.title.trim() : "";
}

export type HeadlineImageState =
  | { status: "none" }
  | { status: "ready"; url: string; alt: string; ref: HeadlineImageRef }
  | { status: "loading"; ref: HeadlineImageRef }
  | { status: "processing"; ref: HeadlineImageRef }
  | { status: "missing"; ref: HeadlineImageRef; reason: string };

export type MediaIndex = { loaded: boolean; failed: boolean; assets: readonly MediaAssetRecord[] };

/** What the detail view shows for the headline picture. Never "nothing": every state has a sentence or a picture. */
export function headlineImageState(ref: HeadlineImageRef | null, media: MediaIndex, imageUrls: Readonly<Record<string, string>>): HeadlineImageState {
  if (!ref) return { status: "none" };
  if (ref.remote) return { status: "ready", url: ref.value, alt: ref.alt, ref };
  const path = ref.mediaPath ?? "";
  const url = imageUrls[path];
  if (url) return { status: "ready", url, alt: ref.alt, ref };
  if (!media.loaded) return { status: "loading", ref };
  if (media.failed) return { status: "missing", ref, reason: "The Story's media list could not be read, so the picture cannot be shown. Reload to try again." };
  const asset = media.assets.find((candidate) => candidate.srcPath === path);
  if (!asset) return { status: "missing", ref, reason: `${ref.key} names ${ref.value}, but this version has no media file with that name.` };
  if (!asset.storagePath) return { status: "processing", ref };
  return { status: "missing", ref, reason: `The file ${asset.storagePath} could not be read from storage.` };
}
