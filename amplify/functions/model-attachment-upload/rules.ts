// What the attachment upload accepts for the visual style profile's example pictures (design: project/wiki/image-toolchain.md section 5.8).
// Pure rules with no AWS in them, so a test can run them without a backend. The handler applies them next to its general checks.

export const VISUAL_ROLES = new Set(["visual_example", "visual_negative"]);
// The profile is one Item lineage; the examples are owned by it, not by one of its versions, so the same picture is one row however often the profile changes.
export const VISUAL_STYLE_OWNER_ID = "item-editorial-doctrine-visual-style";
export const VISUAL_STYLE_SLUG = "editorial-doctrine-visual-style";
export const MAX_VISUAL_BYTES = 10 * 1024 * 1024; // the newsroom editor's own MAX_IMAGE_BYTES; the general cap is 25 MB
// Providers take raster images, so SVG is not accepted.
export const VISUAL_MEDIA_TYPES: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" };

// A generated picture kept with its round (src/papyrus_content/images/candidate_store.py PICTURE_ROLE); it takes the same raster types and the general size cap.
export const CANDIDATE_PICTURE_ROLE = "image_candidate_file";

// Guideline documents (src/papyrus_content/guidelines/store.py ROLE and ASSET_ROLE): the document is one JSON file, so it takes the general types and the general cap;
// a file the document names (a design system's font) is bytes of no declared type, so it takes application/octet-stream and nothing else.
export const DOCTRINE_DOCUMENT_ROLE = "doctrine_document";
export const DOCTRINE_ASSET_ROLE = "doctrine_asset";
export const OCTET_STREAM_ROLES = new Set([DOCTRINE_ASSET_ROLE]);
export const OCTET_STREAM_MEDIA_TYPE = "application/octet-stream";

export function isVisualRole(role: string): boolean {
  return VISUAL_ROLES.has(role);
}

export type VisualInput = { ownerKind: string; ownerId: string; role: string; mediaType: string; byteSize: number; sha256: string | null; sortKey: string; filename: string };

/** Throws a plain-words error when a visual role's upload breaks a rule. Other roles are not touched here. */
export function assertVisualUpload(input: VisualInput): void {
  if (input.ownerKind !== "item" || input.ownerId !== VISUAL_STYLE_OWNER_ID) {
    throw new Error(`Example pictures belong to the visual style profile (item ${VISUAL_STYLE_OWNER_ID}).`);
  }
  if (!(input.mediaType in VISUAL_MEDIA_TYPES)) throw new Error("Example pictures must be PNG, JPEG or WebP.");
  if (input.byteSize > MAX_VISUAL_BYTES) throw new Error("Example pictures must be 10 MB or smaller.");
  if (!input.sha256) throw new Error("Example pictures need a sha256, which names the stored file so the same picture is kept once.");
  if (input.sortKey !== input.sha256) throw new Error("An example picture's sortKey must be its sha256.");
  const expected = `${input.sha256}.${VISUAL_MEDIA_TYPES[input.mediaType]}`;
  if (input.filename !== expected) throw new Error(`An example picture's filename must be ${expected}.`);
}

/** The image media types are for the visual roles and generated candidate pictures only; no other role may start taking pictures. Guideline asset files take raw bytes only. */
export function mediaTypeAllowedForRole(role: string, mediaType: string, generalTypes: Set<string>): boolean {
  if (OCTET_STREAM_ROLES.has(role)) return mediaType === OCTET_STREAM_MEDIA_TYPE;
  return isVisualRole(role) || role === CANDIDATE_PICTURE_ROLE ? mediaType in VISUAL_MEDIA_TYPES : generalTypes.has(mediaType);
}

/** Image file sizes have their own cap; every other role keeps the general one. */
export function byteLimitForRole(role: string, general: number): number {
  return isVisualRole(role) ? MAX_VISUAL_BYTES : general;
}
