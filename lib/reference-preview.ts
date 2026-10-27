/**
 * What a Reference card shows besides its title: the source page's preview image, a one-line dek and the site name.
 *
 * Storage: a `ReferenceAttachment` with role "preview" (sort key "002-preview"), no schema change. `sourceUri` is the
 * page's og:image / twitter:image address and `metadata` holds `{ description, siteName, title, fetchedAt }`. The newsroom
 * already loads every attachment with the References, so the feed needs no extra request. `papyrus references enrich-images`
 * (src/papyrus_content/reference_images.py) writes them.
 */
import type { ReferenceAttachmentRecord, ReferenceRecord } from "./category-repository";

export const REFERENCE_PREVIEW_ROLE = "preview";

export type ReferencePreview = {
  imageUrl: string | null;
  description: string | null;
  siteName: string | null;
  title: string | null;
};

function record(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try { return record(JSON.parse(value)); } catch { return {}; }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function httpAddress(value: unknown): string | null {
  const candidate = text(value);
  return candidate && /^https?:\/\//i.test(candidate) ? candidate : null;
}

/** The preview of each Reference lineage, from its "preview" attachment. A lineage with none has no entry. */
export function referencePreviewsByLineage(attachments: ReferenceAttachmentRecord[] | undefined): Map<string, ReferencePreview> {
  const previews = new Map<string, ReferencePreview>();
  for (const attachment of attachments ?? []) {
    if (attachment.role !== REFERENCE_PREVIEW_ROLE || !attachment.referenceLineageId) continue;
    const metadata = record(attachment.metadata);
    previews.set(attachment.referenceLineageId, {
      imageUrl: httpAddress(attachment.sourceUri) ?? httpAddress(metadata.imageUrl),
      description: text(metadata.description),
      siteName: text(metadata.siteName),
      title: text(metadata.title),
    });
  }
  return previews;
}

/** The one-line dek: the source page's description, else a summary recorded on the Reference. */
export function referenceDek(reference: ReferenceRecord, preview: ReferencePreview | undefined): string | null {
  if (preview?.description) return preview.description;
  const metadata = record(reference.metadata);
  for (const key of ["subtitle", "summary", "abstract", "description"]) {
    const value = text(metadata[key]);
    if (value) return value;
  }
  return null;
}

/** The source's host without "www.", or null when the Reference has no web address. */
export function referenceSourceHost(reference: ReferenceRecord): string | null {
  const candidate = httpAddress(reference.sourceUri);
  if (!candidate) return null;
  try { return new URL(candidate).hostname.replace(/^www\./i, "") || null; } catch { return null; }
}

/** Short age for a card: "5m", "3h", "2d", "6w", "4mo". */
export function formatFeedAge(time: number | null, now: number): string | null {
  if (time === null) return null;
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days}d`;
  if (days < 60) return `${Math.round(days / 7)}w`;
  return `${Math.round(days / 30)}mo`;
}

function words(text: string): string[] {
  return text.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, " ").split(" ").filter((word) => word.length > 1);
}

/**
 * Whether the dek tells the reader something the headline and picture do not. A dek that repeats the headline, or that is mostly
 * the headline's own words, is dropped; so is the description of a GitHub repository, whose social-card picture already prints it.
 */
export function dekAddsInformation(title: string, dek: string | null, imageUrl: string | null): boolean {
  if (!dek) return false;
  let imageHost = "";
  try { imageHost = imageUrl ? new URL(imageUrl).hostname : ""; } catch { /* no host */ }
  if (/(^|\.)opengraph\.githubassets\.com$/i.test(imageHost)) return false;
  const titleWords = new Set(words(title));
  const dekWords = words(dek);
  if (!dekWords.length) return false;
  const shared = dekWords.filter((word) => titleWords.has(word)).length;
  const covered = titleWords.size ? [...titleWords].filter((word) => dekWords.includes(word)).length / titleWords.size : 0;
  return shared / dekWords.length < 0.6 && covered < 0.8;
}
